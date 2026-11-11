"""Perfilador de tablas CSV: la primera revisión de una tabla que nunca has visto.

Automatiza la lista de preguntas que conviene hacerle a cualquier tabla antes de
modelarla, y devuelve un informe en Markdown con las SEÑALES ordenadas por gravedad.
No arregla nada ni decide nada: solo señala dónde mirar. Lo que significa cada señal
(¿error o regla de negocio?) lo decide quien conoce el dominio.

Qué revisa
  - Grano y llave: filas vs. llaves distintas, duplicados exactos y duplicados con
    contenido distinto.
  - CDC (si hay columnas _ab_cdc_*): versiones por llave, LSN repetidos, borrados y
    consistencia entre el orden por LSN y por fecha de actualización.
  - Cada columna: tipo inferido, nulos y blancos, cardinalidad, valores frecuentes
    (entre corchetes, para ver espacios), mayúsculas/espacios mezclados, tipos mezclados,
    formatos de fecha distintos, valores centinela (1900-01-01, -1, 'N/A', ...),
    rangos y fechas futuras.
  - Relaciones: valores sin correspondencia en otra tabla (huérfanos).
  - Coherencia entre columnas: por ejemplo, que la fecha real no sea posterior a la final.

Con columnas CDC y una llave, las columnas se perfilan sobre el ESTADO VIGENTE (última
versión por LSN, sin borrados), porque es lo que verá el negocio. Usa --crudo para perfilar
todas las filas tal como llegaron.

Ejemplos (desde la raíz del repo, con el entorno virtual activo)
  python tools/perfilar_tabla.py data/replica/carga_1/fle_viaje.csv --llave IdViaje
  python tools/perfilar_tabla.py data/replica/carga_1/fle_viaje_det.csv \\
      --llave IdViaje,IdPartida \\
      --rel ClaCliente=data/replica/carga_1/vta_cliente.csv:ClaCliente
  python tools/perfilar_tabla.py data/replica/carga_1/fle_viaje.csv --llave IdViaje \\
      --orden "FechaRealEmbarque<=FechaEmbarqueFinal" --salida /ruta/perfil.md

Solo usa duckdb (ya está en requirements.txt) y lee los archivos en modo lectura.
"""
import argparse
import sys
from pathlib import Path

import duckdb

# Valores que suelen significar "dato no capturado" aunque no sean NULL.
# (La cadena vacía no va aquí: DuckDB ya la lee como NULL y se reporta como nulo/blanco.)
SENTINELAS_TEXTO = ("NULL", "NONE", "N/A", "NA", "NAN", "-", "--", "?", "S/D",
                    "SIN DATO", "NO APLICA", "NULO", "VACIO", "VACÍO")
SENTINELAS_FECHA = ("1900-01-01", "0001-01-01", "1970-01-01", "9999-12-31",
                    "2999-12-31", "0000-00-00")
SENTINELAS_NUM = ("-1", "-9", "-99", "-999", "-9999", "9999", "99999", "999999")

ORDEN_NIVEL = {"ALTA": 0, "MEDIA": 1, "INFO": 2}
PROPORCION_TIPO = 0.98  # una columna es "numérica" si al menos 98 % de sus valores lo son


def q(nombre: str) -> str:
    """Identificador SQL entre comillas dobles."""
    return '"' + nombre.replace('"', '""') + '"'


def lit(texto) -> str:
    """Literal de texto SQL."""
    return "'" + str(texto).replace("'", "''") + "'"


def md(valor) -> str:
    """Celda de tabla Markdown."""
    s = "" if valor is None else str(valor)
    return s.replace("|", "\\|").replace("\n", " ")


def tabla(columnas, filas) -> str:
    out = ["| " + " | ".join(columnas) + " |", "|" + "---|" * len(columnas)]
    out += ["| " + " | ".join(md(v) for v in f) + " |" for f in filas]
    return "\n".join(out)


def lista_sql(valores) -> str:
    return ", ".join(lit(v) for v in valores)


class Informe:
    def __init__(self):
        self.senales = []      # (nivel, texto)
        self.secciones = []    # texto Markdown

    def senal(self, nivel, texto):
        self.senales.append((nivel, texto))

    def seccion(self, texto):
        self.secciones.append(texto)

    def render(self, titulo, nota) -> str:
        orden = sorted(self.senales, key=lambda s: ORDEN_NIVEL[s[0]])
        cab = ["# Perfil de %s" % titulo, "", nota, "", "## Señales (de mayor a menor gravedad)", ""]
        if orden:
            cab += ["- **[%s]** %s" % (n, t) for n, t in orden]
        else:
            cab.append("_Sin señales: la tabla se ve limpia con estas revisiones._")
        return "\n".join(cab) + "\n\n" + "\n\n".join(self.secciones) + "\n"


def perfil_columna(con, col, max_valores, informe):
    """Perfila una columna de la vista `t`. Devuelve la fila resumen y el detalle en Markdown."""
    c = q(col)
    f = con.execute("""
        select count(*) filas,
               sum((%(c)s is null)::int) nulos,
               sum((%(c)s is not null and trim(%(c)s) = '')::int) blancos,
               count(distinct %(c)s) distintos,
               count(distinct upper(trim(%(c)s))) distintos_norm,
               sum((%(c)s is not null and %(c)s <> trim(%(c)s))::int) con_espacios,
               sum((try_cast(trim(%(c)s) as bigint) is not null)::int) n_int,
               sum((try_cast(trim(%(c)s) as double) is not null)::int) n_num,
               sum((regexp_matches(trim(%(c)s), '^[0-9]{4}-[0-9]{2}-[0-9]{2}')
                    and try_cast(trim(%(c)s) as timestamp) is not null)::int) n_fecha,
               sum((upper(trim(%(c)s)) in (%(st)s))::int) n_sent_texto,
               sum((substr(trim(%(c)s), 1, 10) in (%(sf)s))::int) n_sent_fecha,
               sum((trim(%(c)s) in (%(sn)s))::int) n_sent_num,
               sum(regexp_matches(trim(%(c)s), '[0-9]')::int) n_digito
        from t""" % {"c": c, "st": lista_sql(SENTINELAS_TEXTO),
                     "sf": lista_sql(SENTINELAS_FECHA), "sn": lista_sql(SENTINELAS_NUM)}).fetchone()
    (filas, nulos, blancos, distintos, dist_norm, con_esp, n_int, n_num, n_fecha,
     s_texto, s_fecha, s_num, n_digito) = [0 if v is None else v for v in f]

    vacios = nulos + blancos
    base = filas - vacios
    if base == 0:
        tipo = "vacía"
    elif n_int >= PROPORCION_TIPO * base:
        tipo = "entero"
    elif n_num >= PROPORCION_TIPO * base:
        tipo = "decimal"
    elif n_fecha >= PROPORCION_TIPO * base:
        tipo = "fecha"
    else:
        tipo = "texto"

    señales_col = []
    mn = mx = None
    # "numérica" incluye columnas con algunos valores basura (se reportan aparte como tipo mezclado)
    numerica = tipo in ("entero", "decimal") or (tipo == "texto" and base and n_num >= 0.5 * base)

    # --- rangos según el tipo -------------------------------------------------------
    if numerica:
        mn, mx, prom, neg, cer = con.execute(
            "select min(try_cast(trim(%(c)s) as double)), max(try_cast(trim(%(c)s) as double)), "
            "avg(try_cast(trim(%(c)s) as double)), "
            "sum((try_cast(trim(%(c)s) as double) < 0)::int), "
            "sum((try_cast(trim(%(c)s) as double) = 0)::int) from t" % {"c": c}).fetchone()
        if neg:
            informe.senal("MEDIA", "`%s`: %d valores negativos (mín. %s)." % (col, neg, mn))
            señales_col.append("%d negativos" % neg)
        if cer:
            informe.senal("INFO", "`%s`: %d ceros." % (col, cer))
    elif tipo == "fecha":
        mn, mx = con.execute(
            "select min(try_cast(trim(%(c)s) as timestamp)), max(try_cast(trim(%(c)s) as timestamp)) "
            "from t" % {"c": c}).fetchone()
        futuras = con.execute(
            "select count(*) from t where try_cast(trim(%(c)s) as timestamp) > current_timestamp" % {"c": c}
        ).fetchone()[0]
        if futuras:
            informe.senal("MEDIA", "`%s`: %d fechas posteriores a hoy (máx. %s)." % (col, futuras, mx))
            señales_col.append("%d futuras" % futuras)
    elif tipo == "texto":
        mn, mx = con.execute("select min(length(%(c)s)), max(length(%(c)s)) from t" % {"c": c}).fetchone()
        mn, mx = "long. %s" % mn, "long. %s" % mx

    # --- señales de calidad --------------------------------------------------------
    if tipo == "vacía":
        informe.senal("INFO", "`%s`: columna completamente vacía." % col)
        señales_col.append("vacía")
    elif vacios:
        informe.senal("INFO", "`%s`: %d nulos o blancos (%.1f %%)." % (col, vacios, 100.0 * vacios / filas))
    if base and distintos == 1:
        informe.senal("INFO", "`%s`: valor constante en toda la tabla." % col)
        señales_col.append("constante")
    if con_esp:
        informe.senal("MEDIA", "`%s`: %d valores con espacios al inicio o al final." % (col, con_esp))
        señales_col.append("espacios")
    if tipo == "texto" and distintos > dist_norm:
        informe.senal("MEDIA", "`%s`: %d valores distintos que son %d tras normalizar mayúsculas y espacios."
                      % (col, distintos, dist_norm))
        señales_col.append("variantes")
    if s_fecha:
        valores = [r[0] for r in con.execute(
            "select distinct substr(trim(%s), 1, 10) from t where substr(trim(%s), 1, 10) in (%s)"
            % (c, c, lista_sql(SENTINELAS_FECHA))).fetchall()]
        informe.senal("ALTA", "`%s`: %d valores centinela de fecha (%s)." % (col, s_fecha, ", ".join(valores)))
        señales_col.append("centinela fecha")
    if s_texto:
        valores = [r[0] for r in con.execute(
            "select distinct trim(%s) from t where upper(trim(%s)) in (%s) limit 5"
            % (c, c, lista_sql(SENTINELAS_TEXTO))).fetchall()]
        informe.senal("MEDIA", "`%s`: %d valores que parecen 'sin dato' (%s)." % (col, s_texto, ", ".join(valores)))
        señales_col.append("'sin dato'")
    if s_num and numerica:
        # un centinela típico (-1, 9999) queda en un extremo del rango; en medio es un dato normal
        candidatos = con.execute(
            "select trim(%(c)s) v, count(*) n from t where trim(%(c)s) in (%(s)s) group by 1" %
            {"c": c, "s": lista_sql(SENTINELAS_NUM)}).fetchall()
        en_extremo = [(v, n) for v, n in candidatos if float(v) in (mn, mx)]
        if en_extremo:
            informe.senal("MEDIA", "`%s`: valores que parecen centinelas numéricos en el extremo del rango (%s)."
                          % (col, ", ".join("%s ×%d" % x for x in en_extremo)))
            señales_col.append("centinela num.")
    # tipos mezclados: casi todo es de un tipo, pero no todo
    ok_num = n_int if tipo == "entero" else n_num
    num_mezclado = (tipo in ("entero", "decimal") and ok_num < base) or \
                   (tipo == "texto" and 0.5 * base <= n_num < base)
    if num_mezclado:
        ejemplos = [r[0] for r in con.execute(
            "select distinct trim(%(c)s) from t where trim(%(c)s) <> '' "
            "and try_cast(trim(%(c)s) as double) is null limit 3" % {"c": c}).fetchall()]
        informe.senal("MEDIA", "`%s`: tipo mezclado, %d de %d valores son numéricos (no lo son: %s)."
                      % (col, n_num, base, ", ".join(ejemplos) or "—"))
        señales_col.append("tipo mezclado")
    fecha_mezclada = (tipo == "fecha" and n_fecha < base) or \
                     (tipo == "texto" and 0.5 * base <= n_fecha < base)
    if fecha_mezclada:
        ejemplos = [r[0] for r in con.execute(
            "select distinct trim(%(c)s) from t where trim(%(c)s) <> '' and not "
            "(regexp_matches(trim(%(c)s), '^[0-9]{4}-[0-9]{2}-[0-9]{2}') "
            "and try_cast(trim(%(c)s) as timestamp) is not null) limit 3" % {"c": c}).fetchall()]
        informe.senal("MEDIA", "`%s`: formato de fecha mezclado, %d de %d valores son fechas ISO (no lo son: %s)."
                      % (col, n_fecha, base, ", ".join(ejemplos) or "—"))
        señales_col.append("fecha mezclada")

    # --- detalle: valores frecuentes y formatos --------------------------------------
    detalle = ["#### `%s` · %s" % (col, tipo)]
    if base:
        limite = distintos if distintos <= max_valores else 5
        titulo_vals = "todos los valores" if distintos <= max_valores else "5 valores más frecuentes"
        filas_v = con.execute(
            "select '[' || %(c)s || ']' valor, count(*) n from t where %(c)s is not null "
            "group by 1 order by 2 desc, 1 limit %(l)d" % {"c": c, "l": limite}).fetchall()
        detalle.append("_%s (entre corchetes, para ver espacios):_" % titulo_vals)
        detalle.append(tabla(["valor", "filas"], filas_v))
        if tipo == "fecha" or (tipo == "texto" and distintos <= 50 and n_digito == base):
            formas = con.execute(
                "select regexp_replace(regexp_replace(trim(%(c)s), '[0-9]+', '9', 'g'), '[A-Za-z]+', 'A', 'g') forma, "
                "count(*) n from t where %(c)s is not null and trim(%(c)s) <> '' group by 1 order by 2 desc limit 6"
                % {"c": c}).fetchall()
            if len(formas) > 1:
                informe.senal("MEDIA", "`%s`: %d formatos distintos (%s)." %
                              (col, len(formas), ", ".join("%s ×%d" % (a, b) for a, b in formas[:3])))
                señales_col.append("formatos")
                detalle.append("_Formatos (9 = racha de dígitos, A = racha de letras):_")
                detalle.append(tabla(["forma", "filas"], formas))

    fila_resumen = [col, tipo, "%d (%.1f %%)" % (vacios, 100.0 * vacios / filas) if filas else "0",
                    distintos, mn if mn is not None else "", mx if mx is not None else "",
                    ", ".join(señales_col)]
    return fila_resumen, "\n\n".join(detalle)


def seccion_llave_y_cdc(con, llave, columnas, informe):
    """Grano, duplicados y semántica CDC sobre las filas crudas (vista `crudo`)."""
    partes = ["## Grano, llave y replicación"]
    total = con.execute("select count(*) from crudo").fetchone()[0]
    exactos = total - con.execute("select count(*) from (select distinct * from crudo)").fetchone()[0]
    filas = [("Filas", total), ("Columnas", len(columnas))]
    if exactos:
        informe.senal("MEDIA", "%d filas son copias exactas de otra (mismo contenido en todas las columnas)." % exactos)
    filas.append(("Filas que son copia exacta de otra", exactos))

    tiene_cdc = "_ab_cdc_lsn" in columnas
    if llave:
        k = ", ".join(q(x) for x in llave)
        n_llaves = con.execute("select count(*) from (select %s from crudo group by %s)" % (k, k)).fetchone()[0]
        sin_llave = con.execute("select count(*) from crudo where %s" %
                                " or ".join("%s is null" % q(x) for x in llave)).fetchone()[0]
        filas += [("Llave", ", ".join(llave)), ("Llaves distintas", n_llaves)]
        if sin_llave:
            informe.senal("ALTA", "%d filas con la llave (%s) nula." % (sin_llave, ", ".join(llave)))
        if not tiene_cdc and n_llaves < total:
            repetidas, distinto = con.execute(
                "select count(*), sum((n_contenidos > 1)::int) from (select count(distinct md5(cast(crudo as varchar))) "
                "n_contenidos from crudo group by %s having count(*) > 1)" % k).fetchone()
            informe.senal("ALTA", "La llave (%s) NO es única: %d llaves se repiten, %d de ellas con contenido distinto."
                          % (", ".join(llave), repetidas, distinto or 0))
        partes.append(tabla(["dato", "valor"], filas))
        if tiene_cdc:
            dist = con.execute(
                "select versiones, count(*) llaves from (select count(*) versiones from crudo group by %s) "
                "group by 1 order by 1" % k).fetchall()
            partes.append("**Versiones por llave:**\n\n" + tabla(["versiones", "llaves"], dist))
            if any(v > 1 for v, _ in dist):
                informe.senal("INFO", "Hay historia de versiones: %d filas para %d llaves; "
                              "ojo con sumar sin quedarse con la última." % (total, n_llaves))
    else:
        partes.append(tabla(["dato", "valor"], filas))

    if tiene_cdc:
        cdc = []
        lsn_rep = con.execute("select count(*) from (select _ab_cdc_lsn from crudo group by 1 having count(*) > 1)"
                              ).fetchone()[0]
        cdc.append(("LSN que aparecen en más de una fila", lsn_rep))
        if "_ab_cdc_deleted_at" in columnas:
            borrados = con.execute("select count(*) from crudo where _ab_cdc_deleted_at is not null").fetchone()[0]
            cdc.append(("Filas de borrado (_ab_cdc_deleted_at)", borrados))
            if borrados:
                informe.senal("MEDIA", "%d filas marcadas como borradas en el origen: excluirlas del estado vigente." % borrados)
        if "_airbyte_extracted_at" in columnas:
            cdc.append(("Extracciones distintas (_airbyte_extracted_at)",
                        con.execute("select count(distinct _airbyte_extracted_at) from crudo").fetchone()[0]))
        if llave and "_ab_cdc_updated_at" in columnas:
            on = " and ".join("a.%s = b.%s" % (q(x), q(x)) for x in llave)
            agrupa = ", ".join("a.%s" % q(x) for x in llave)
            mismo_orden = ("try_cast(a._ab_cdc_lsn as bigint) < try_cast(b._ab_cdc_lsn as bigint)")
            contradice = con.execute(
                "select count(*) from (select %s from crudo a join crudo b on %s and %s "
                "and a._ab_cdc_updated_at > b._ab_cdc_updated_at group by %s)"
                % (agrupa, on, mismo_orden, agrupa)).fetchone()[0]
            empates = con.execute(
                "select count(*) from (select %s from crudo a join crudo b on %s and %s "
                "and a._ab_cdc_updated_at = b._ab_cdc_updated_at group by %s)"
                % (agrupa, on, mismo_orden, agrupa)).fetchone()[0]
            cdc.append(("Llaves donde el LSN y la fecha de actualización se CONTRADICEN", contradice))
            cdc.append(("Llaves con versiones de LSN distinto y la MISMA fecha de actualización", empates))
            if contradice:
                informe.senal("ALTA", "En %d llaves una versión con LSN menor tiene fecha de actualización mayor: "
                              "el orden por LSN y por fecha se contradicen; decidir cuál manda." % contradice)
            if empates:
                informe.senal("MEDIA", "En %d llaves hay versiones con LSN distinto y la misma fecha de actualización: "
                              "la fecha no basta para ordenar; usar el LSN como criterio principal." % empates)
        partes.append("**Columnas CDC:**\n\n" + tabla(["dato", "valor"], cdc))
    return "\n\n".join(partes)


def seccion_relaciones(con, relaciones, informe):
    if not relaciones:
        return None
    partes = ["## Relaciones (valores sin correspondencia)"]
    for i, rel in enumerate(relaciones):
        try:
            izq, resto = rel.split("=", 1)
            archivo, der = resto.rsplit(":", 1)
        except ValueError:
            raise SystemExit("--rel debe tener la forma columna=ruta.csv:columna_referencia (recibí %r)" % rel)
        con.execute("create or replace view ref_%d as select * from read_csv(%s, all_varchar=true, header=true)"
                    % (i, lit(archivo)))
        n, distintos = con.execute(
            "select count(*), count(distinct trim(%(a)s)) from t where %(a)s is not null and trim(%(a)s) <> '' "
            "and trim(%(a)s) not in (select trim(%(b)s) from ref_%(i)d where %(b)s is not null)"
            % {"a": q(izq), "b": q(der), "i": i}).fetchone()
        titulo = "`%s` → `%s` de `%s`" % (izq, der, Path(archivo).name)
        if n:
            ejemplos = con.execute(
                "select trim(%(a)s) valor, count(*) filas from t where %(a)s is not null and trim(%(a)s) <> '' "
                "and trim(%(a)s) not in (select trim(%(b)s) from ref_%(i)d where %(b)s is not null) "
                "group by 1 order by 2 desc limit 10" % {"a": q(izq), "b": q(der), "i": i}).fetchall()
            informe.senal("ALTA", "%s: %d filas (%d valores distintos) no existen en la tabla de referencia."
                          % (titulo, n, distintos))
            partes.append("**%s**: %d filas huérfanas, %d valores distintos.\n\n" % (titulo, n, distintos)
                          + tabla(["valor huérfano", "filas"], ejemplos))
        else:
            partes.append("**%s**: todos los valores existen en la referencia." % titulo)
    return "\n\n".join(partes)


def seccion_orden(con, reglas, llave, informe):
    if not reglas:
        return None
    partes = ["## Coherencia entre columnas"]
    k = ", ".join(q(x) for x in llave) if llave else None
    for regla in reglas:
        if "<=" not in regla:
            raise SystemExit("--orden debe tener la forma 'columnaA<=columnaB' (recibí %r)" % regla)
        a, b = [x.strip() for x in regla.split("<=", 1)]
        cond = ("try_cast(trim(%(a)s) as timestamp) > try_cast(trim(%(b)s) as timestamp)" % {"a": q(a), "b": q(b)})
        comparables = con.execute(
            "select count(*) from t where try_cast(trim(%(a)s) as timestamp) is not null "
            "and try_cast(trim(%(b)s) as timestamp) is not null" % {"a": q(a), "b": q(b)}).fetchone()[0]
        viola = con.execute("select count(*) from t where %s" % cond).fetchone()[0]
        partes.append("**%s <= %s**: %d de %d filas comparables la violan." % (a, b, viola, comparables))
        if viola:
            informe.senal("ALTA", "%s debería ser <= %s, pero %d filas lo violan." % (a, b, viola))
            cols = ([k] if k else []) + [q(a), q(b)]
            ej = con.execute("select %s from t where %s limit 5" % (", ".join(cols), cond))
            partes.append(tabla([d[0] for d in ej.description], ej.fetchall()))
    return "\n\n".join(partes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="ruta del CSV (acepta comodines, p. ej. 'data/replica/carga_*/fle_viaje.csv')")
    ap.add_argument("--llave", help="columnas que forman la llave, separadas por coma (grano esperado)")
    ap.add_argument("--rel", action="append", default=[], metavar="COL=CSV:COL_REF",
                    help="relación a verificar (se puede repetir)")
    ap.add_argument("--orden", action="append", default=[], metavar="'A<=B'",
                    help="regla de orden entre dos columnas de fecha (se puede repetir)")
    ap.add_argument("--crudo", action="store_true",
                    help="perfilar todas las filas tal como llegaron, sin reducir al estado vigente")
    ap.add_argument("--max-valores", type=int, default=12,
                    help="hasta cuántos valores distintos se listan completos por columna (def. 12)")
    ap.add_argument("--salida", help="guardar el informe en este archivo Markdown además de imprimirlo")
    args = ap.parse_args()

    con = duckdb.connect()
    try:
        con.execute("create view crudo as select * from read_csv(%s, all_varchar=true, header=true)" % lit(args.csv))
    except duckdb.Error as e:
        print("No pude leer %s: %s" % (args.csv, e), file=sys.stderr)
        return 2
    columnas = [r[0] for r in con.execute("describe crudo").fetchall()]
    llave = [x.strip() for x in args.llave.split(",")] if args.llave else []
    faltan = [x for x in llave if x not in columnas]
    if faltan:
        print("La llave menciona columnas que no existen: %s. Columnas: %s" % (faltan, columnas), file=sys.stderr)
        return 2

    # Vista `t`: estado vigente si hay CDC y llave; si no, las filas tal cual.
    vigente = bool(llave) and "_ab_cdc_lsn" in columnas and not args.crudo
    if vigente:
        k = ", ".join(q(x) for x in llave)
        borrado = "and _ab_cdc_deleted_at is null" if "_ab_cdc_deleted_at" in columnas else ""
        orden_fecha = ", _ab_cdc_updated_at desc nulls last" if "_ab_cdc_updated_at" in columnas else ""
        con.execute("create view t as select * exclude (rn) from (select *, row_number() over ("
                    "partition by %s order by try_cast(_ab_cdc_lsn as bigint) desc nulls last%s) rn from crudo) "
                    "where rn = 1 %s" % (k, orden_fecha, borrado))
        n_t = con.execute("select count(*) from t").fetchone()[0]
        nota = ("Columnas perfiladas sobre el **estado vigente** (última versión por LSN, sin borrados): "
                "%d filas. Usa `--crudo` para perfilar todas las filas." % n_t)
    else:
        con.execute("create view t as select * from crudo")
        nota = "Columnas perfiladas sobre **todas las filas** tal como llegaron."

    informe = Informe()
    informe.seccion(seccion_llave_y_cdc(con, llave, columnas, informe))

    resumen, detalles = [], []
    for col in columnas:
        fila, detalle = perfil_columna(con, col, args.max_valores, informe)
        resumen.append(fila)
        detalles.append(detalle)
    informe.seccion("## Columnas\n\n" + tabla(
        ["columna", "tipo inferido", "nulos o blancos", "distintos", "mínimo", "máximo", "señales"], resumen))

    for extra in (seccion_relaciones(con, args.rel, informe), seccion_orden(con, args.orden, llave, informe)):
        if extra:
            informe.seccion(extra)
    informe.seccion("## Detalle por columna\n\n" + "\n\n".join(detalles))

    texto = informe.render(Path(args.csv).name, nota)
    print(texto)
    if args.salida:
        Path(args.salida).write_text(texto)
        print("Informe guardado en %s" % args.salida, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
