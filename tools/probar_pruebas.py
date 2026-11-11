"""Prueba de las pruebas (mutation testing).

Una prueba que nunca falla no protege nada. Este script mete errores A PROPÓSITO en los
modelos (en una copia temporal; el repositorio y su deacero.duckdb no se tocan) y comprueba
que al menos una prueba automática los detecta.

Uso (desde la raíz del repo, con el entorno virtual activo):
    python tools/probar_pruebas.py                 # imprime una tabla en Markdown
    python tools/probar_pruebas.py --dir /ruta     # carpeta temporal alternativa

Un mutante "sobrevive" si ninguna prueba falla: es una laguna de cobertura (o un cambio que
no altera el resultado con los datos actuales). Se reporta tal cual, sin esconderlo.
"""
import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comun import copiar_proyecto, correr_dbt, fallidos  # noqa: E402

# (nombre, regla que viola, [(archivo, texto_original, texto_con_error), ...])
MUTANTES = [
    ("Flete multiplicado por partidas (sin agregar antes del join)", "Regla 4",
     [("models/gold/fct_embarques.sql", "count(*)       as num_partidas,", "1              as num_partidas,"),
      ("models/gold/fct_embarques.sql", "sum(peso_kg)   as peso_kg_total", "peso_kg        as peso_kg_total"),
      ("models/gold/fct_embarques.sql", "    group by id_viaje\n", "")]),
    ("Cuenta viajes programados (PRO) como embarcados", "Regla 2",
     [("models/silver/int_viajes__embarcados.sql", "where estatus in ('TRA', 'ENT')", "where estatus <> 'CAN'")]),
    ("Prioriza la fecha final sobre la real", "Regla 1",
     [("models/silver/int_viajes__embarcados.sql",
       "coalesce(fecha_real_embarque, fecha_embarque_final)", "coalesce(fecha_embarque_final, fecha_real_embarque)")]),
    ("A tiempo comparando timestamps en vez de fechas", "Regla 5",
     [("models/silver/int_viajes__puntualidad.sql",
       "(cast(e.fecha_entrega as date) <= cast(v.fecha_compromiso as date))", "(e.fecha_entrega <= v.fecha_compromiso)")]),
    ("Usa el segmento ACTUAL del cliente en vez del vigente al embarque", "Regla 6",
     [("models/silver/int_partidas__segmento.sql",
       "        and p.fecha_embarque >= t.vigente_desde\n        and (t.vigente_hasta is null or p.fecha_embarque < t.vigente_hasta)",
       "        and t.vigente_hasta is null")]),
    ("Descarta las toneladas de clientes no identificados", "Regla 7",
     [("models/gold/fct_partidas_embarque.sql", "    on s.id_viaje = f.id_viaje",
       "    on s.id_viaje = f.id_viaje\nwhere s.segmento_cliente <> 'NO_IDENTIFICADO'")]),
    ("Toneladas = kg / 1024 en vez de / 1000", "Regla 3",
     [("models/gold/fct_embarques.sql", "/ 1000 as decimal(18, 3)", "/ 1024 as decimal(18, 3)")]),
    ("No excluye viajes borrados en el origen", "CDC",
     [("models/staging/stg_fle__viajes.sql", "where orden_version = 1\n  and cdc_eliminado_en is null", "where orden_version = 1")]),
    ("Se queda con la versión MÁS VIEJA del viaje", "CDC",
     [("models/staging/stg_fle__viajes.sql",
       "order by cdc_lsn desc, cdc_actualizado_en desc, extraido_en desc",
       "order by cdc_lsn asc, cdc_actualizado_en asc, extraido_en asc")]),
    ("Se queda con la versión MÁS VIEJA del POD (ignora correcciones)", "CDC",
     [("models/staging/stg_fle__entregas.sql",
       "order by cdc_lsn desc, cdc_actualizado_en desc, extraido_en desc",
       "order by cdc_lsn asc, cdc_actualizado_en asc, extraido_en asc")]),
    ("Ignora la zona horaria al fechar el cambio de segmento (usa UTC)", "Regla 6",
     [("macros/a_fecha_local.sql",
       "cast(timezone('America/Monterrey', timezone('UTC', {{ columna_utc }})) as date)",
       "cast({{ columna_utc }} as date)")]),
    ("No normaliza el texto del segmento (espacios y mayúsculas)", "Limpieza",
     [("models/staging/stg_vta__clientes.sql", "upper(trim(Segmento))", "Segmento")]),
    ("Incluye en cumplimiento viajes SIN POD", "Regla 5",
     [("models/marts/cumplimiento_entrega.sql", "where tiene_pod\n", "")]),
    ("No limpia la fecha centinela 1900-01-01", "Limpieza",
     [("models/staging/stg_fle__viajes.sql",
       "nullif(cast(FechaRealEmbarque as timestamp), cast('1900-01-01' as timestamp))",
       "cast(FechaRealEmbarque as timestamp)")]),
]


def aplicar(proyecto: Path, cambios) -> None:
    for archivo, viejo, nuevo in cambios:
        ruta = proyecto / archivo
        texto = ruta.read_text()
        if viejo not in texto:  # el mutante quedó desfasado respecto al código: avisar fuerte
            raise SystemExit("No se encontró el texto a mutar en %s:\n%s" % (archivo, viejo))
        ruta.write_text(texto.replace(viejo, nuevo, 1))


def ejecutar(proyecto: Path) -> list:
    """Corre `dbt run` y luego `dbt test` y devuelve TODO lo que falló.

    Se evita `dbt build` a propósito: build se detiene en la primera falla y SALTA lo que
    depende de ella, por lo que las pruebas de negocio de más abajo nunca se evaluarían.
    Aquí cada prueba se evalúa por separado, para medir la defensa en profundidad.
    (En producción conviene build: frena la publicación de datos malos.)
    """
    correr_dbt(proyecto, "run")
    fallas = fallidos(proyecto)          # errores de ejecución de modelos
    correr_dbt(proyecto, "test")
    return sorted(set(fallas + fallidos(proyecto)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="carpeta donde crear las copias temporales")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(dir=args.dir) as tmp:
        base = Path(tmp)

        # 0. Línea base: sin sabotaje todo debe pasar; si no, la tabla no significaría nada.
        p0 = copiar_proyecto(base / "base")
        malos = ejecutar(p0)
        if malos:
            print("La línea base ya falla, no se puede evaluar: %s" % malos)
            return 2

        filas, vivos = [], 0
        for i, (nombre, regla, cambios) in enumerate(MUTANTES, 1):
            p = copiar_proyecto(base / ("m%02d" % i))
            aplicar(p, cambios)
            detectan = ejecutar(p)
            estado = "detectado" if detectan else "SOBREVIVE"
            vivos += 0 if detectan else 1
            filas.append((nombre, regla, estado, detectan))
            print("[%2d/%d] %-9s %s" % (i, len(MUTANTES), estado, nombre), file=sys.stderr)

    print("| # | Error introducido a propósito | Regla | Resultado | Pruebas que lo detectan |")
    print("|---|---|---|---|---|")
    for i, (nombre, regla, estado, detectan) in enumerate(filas, 1):
        quien = ", ".join("`%s`" % d for d in detectan[:4]) + (" …" if len(detectan) > 4 else "")
        print("| %d | %s | %s | %s | %s |" % (i, nombre, regla, estado, quien or "—"))
    print("\n%d de %d errores detectados; %d sobreviven." % (len(filas) - vivos, len(filas), vivos))
    return 1 if vivos else 0


if __name__ == "__main__":
    sys.exit(main())
