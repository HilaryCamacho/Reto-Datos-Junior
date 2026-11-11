"""Genera reporte/dashboard.html: tablero de los marts y de los hallazgos de calidad de datos.

El HTML resultante es AUTOCONTENIDO (CSS, SVG y un poco de JavaScript en el mismo archivo;
ninguna librería ni recurso externo): se abre con doble clic, sin internet y sin instalar nada.

Lee, en solo lectura:
  - deacero.duckdb          -> los marts y las capas que los alimentan (requiere `dbt build`)
  - reporte/impacto_hallazgos.json -> impacto de cada hallazgo (python tools/analisis_impacto.py)

La salida es DETERMINISTA (mismos datos, mismo archivo, byte por byte), así que el CI puede
regenerarlo y comprobar que el archivo versionado no quedó desactualizado.

Uso (desde la raíz del repo, con el entorno virtual activo):
    python tools/generar_dashboard.py
"""
import argparse
import html
import json
import math
import sys
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent.parent
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
SEGMENTOS = ["DISTRIBUIDOR", "CONSTRUCTORA", "INDUSTRIAL", "NO_IDENTIFICADO"]
SEG_NOMBRE = {"DISTRIBUIDOR": "Distribuidor", "CONSTRUCTORA": "Constructora",
              "INDUSTRIAL": "Industrial", "NO_IDENTIFICADO": "No identificado"}
# Color por entidad (no por posición): cada segmento conserva su color en todo el tablero.
# "No identificado" no es una serie con identidad propia: va en gris (de-énfasis).
SEG_COLOR = {"DISTRIBUIDOR": "var(--s1)", "CONSTRUCTORA": "var(--s2)",
             "INDUSTRIAL": "var(--s3)", "NO_IDENTIFICADO": "var(--muted)"}

# --- paleta (referencia validada con validate_palette.js: ver README) --------------------------
CLARO = {"page": "#f9f9f7", "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
         "grid": "#e1e0d9", "axis": "#c3c2b7", "border": "rgba(11,11,11,0.10)", "good": "#006300",
         "s1": "#2a78d6", "s2": "#eb6834", "s3": "#1baf7a",
         # secuencial azul de menor a mayor valor (pasos 100,200,300,400,500,600,700)
         "q": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
         # ordinal para el embudo (pasos 250,350,450,550,650)
         "o": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]}
OSCURO = {"page": "#0d0d0d", "surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
          "grid": "#2c2c2a", "axis": "#383835", "border": "rgba(255,255,255,0.10)", "good": "#0ca30c",
          "s1": "#3987e5", "s2": "#d95926", "s3": "#199e70",
          # en oscuro "más" = más claro; lo bajo se acerca a la superficie
          "q": ["#0d366b", "#104281", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
          "o": ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"]}


# --- utilidades ---------------------------------------------------------------------------------
def esc(x):
    return html.escape(str(x), quote=True)


def n0(x):
    return "{:,.0f}".format(x)


def n1(x):
    return "{:,.1f}".format(x)


def n2(x):
    return "{:,.2f}".format(x)


def c1(x):
    return "{:.1f}".format(x)


def mes_largo(am):
    anio, m = am.split("-")
    return "%s %s" % (MESES[int(m) - 1], anio)


def mes_tick(am):
    return MESES[int(am.split("-")[1]) - 1]


def _lum(h):
    r, g, b = [int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def tinta_sobre(fondo):
    """Texto blanco o casi negro, el que dé más contraste sobre `fondo` (WCAG)."""
    def ratio(a, b):
        la, lb = sorted([_lum(a), _lum(b)], reverse=True)
        return (la + 0.05) / (lb + 0.05)
    return "#ffffff" if ratio(fondo, "#ffffff") >= ratio(fondo, "#0b0b0b") else "#0b0b0b"


def maximo_agradable(v):
    exp = 10 ** math.floor(math.log10(v))
    for k in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v / exp <= k:
            return k * exp
    return 10 * exp


def paso_q(v, lo, hi):
    """Clase secuencial 0..6 de un valor dentro de [lo, hi]."""
    if hi == lo:
        return 3
    return min(6, int((v - lo) / (hi - lo) * 7))


# --- carga de datos -----------------------------------------------------------------------------
def cargar(db, ruta_impacto):
    con = duckdb.connect(str(db), read_only=True)

    def filas(sql):
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        return [{k: (float(v) if hasattr(v, "as_tuple") else v) for k, v in zip(cols, r)}
                for r in cur.fetchall()]

    d = {}
    d["emb"] = filas("select * from mart_logistica.embarques_mensual order by anio_mes, cla_planta")
    d["cum"] = filas("select * from mart_logistica.cumplimiento_entrega order by anio_mes, segmento_cliente")
    d["embudo"] = {
        "filas": con.execute("select count(*) from landing_fle.fle_viaje").fetchone()[0],
        "unicos": con.execute("select count(distinct IdViaje) from landing_fle.fle_viaje").fetchone()[0],
        "vigentes": con.execute("select count(*) from staging.stg_fle__viajes").fetchone()[0],
        "embarcados": con.execute("select count(*) from gold_logistica.fct_embarques").fetchone()[0],
        "con_pod": con.execute("select count(*) from gold_logistica.fct_embarques where tiene_pod").fetchone()[0],
    }
    d["impacto"] = json.loads(Path(ruta_impacto).read_text())
    return d


# --- piezas de SVG ------------------------------------------------------------------------------
def barra_redondeada(x, y, w, h, r=4):
    """Barra con la punta redondeada (4 px) y la base recta, anclada a la línea base."""
    if h <= r:
        return "M%s,%sH%sV%sH%sZ" % (c1(x), c1(y + h), c1(x + w), c1(y), c1(x))
    return ("M%s,%s V%s Q%s,%s %s,%s H%s Q%s,%s %s,%s V%s Z"
            % (c1(x), c1(y + h), c1(y + r), c1(x), c1(y), c1(x + r), c1(y), c1(x + w - r),
               c1(x + w), c1(y), c1(x + w), c1(y + r), c1(y + h)))


def sparkline(valores):
    W, H, p = 120, 32, 4
    lo, hi = min(valores), max(valores)
    span = (hi - lo) or 1
    pts = [(p + i * (W - 2 * p) / (len(valores) - 1), H - p - (v - lo) / span * (H - 2 * p))
           for i, v in enumerate(valores)]
    ruta = "M" + " L".join("%s,%s" % (c1(x), c1(y)) for x, y in pts)
    return ('<svg class="spark" viewBox="0 0 %d %d" aria-hidden="true"><path d="%s" class="sp-line"/>'
            '<circle cx="%s" cy="%s" r="4" class="sp-dot"/></svg>' % (W, H, ruta, c1(pts[-1][0]), c1(pts[-1][1])))


def panel_toneladas(nombre, filas, ymax, total):
    W, H = 360, 214
    ml, mr, mt, mb = 48, 12, 36, 30
    pw, ph = W - ml - mr, H - mt - mb
    slot = pw / len(filas)
    bw = 24
    p = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Toneladas embarcadas por mes, %s">' % (W, H, esc(nombre))]
    p.append('<text x="%d" y="16" class="t-ink t-title">%s</text>' % (ml, esc(nombre)))
    p.append('<text x="%d" y="16" class="t-sec" text-anchor="end">%s t en el semestre</text>' % (W - mr, n0(total)))
    for t in (0, ymax / 2, ymax):
        y = mt + ph - ph * t / ymax
        p.append('<line x1="%d" x2="%d" y1="%s" y2="%s" class="%s"/>' % (ml, W - mr, c1(y), c1(y), "ax" if t == 0 else "gl"))
        p.append('<text x="%d" y="%s" text-anchor="end" class="t-mut">%s</text>' % (ml - 8, c1(y + 4), n0(t)))
    imax = max(range(len(filas)), key=lambda i: filas[i]["toneladas_embarcadas"])
    for i, f in enumerate(filas):
        cx = ml + slot * (i + 0.5)
        h = ph * f["toneladas_embarcadas"] / ymax
        y = mt + ph - h
        tip = "\n".join([mes_largo(f["anio_mes"]), "Toneladas|%s t" % n1(f["toneladas_embarcadas"]),
                         "Viajes|%s" % n0(f["num_viajes"]), "Flete|$%s MXN" % n0(f["costo_flete_mxn"]),
                         "Flete por tonelada|$%s" % n2(f["costo_flete_por_ton"])])
        p.append('<g class="mark" tabindex="0" data-tip="%s"><rect x="%s" y="%d" width="%s" height="%d" fill="transparent"/>'
                 '<path class="bar" d="%s"/></g>'
                 % (esc("%s · %s\n%s" % (nombre, tip.split("\n")[0], "\n".join(tip.split("\n")[1:]))),
                    c1(cx - slot / 2), mt, c1(slot), ph, barra_redondeada(cx - bw / 2, y, bw, h)))
        p.append('<text x="%s" y="%d" text-anchor="middle" class="t-mut">%s</text>' % (c1(cx), mt + ph + 18, mes_tick(f["anio_mes"])))
        if i == imax:
            p.append('<text x="%s" y="%s" text-anchor="middle" class="t-sec t-val">%s</text>'
                     % (c1(cx), c1(y - 6), n0(f["toneladas_embarcadas"])))
    p.append("</svg>")
    return "".join(p)


def mapa_calor(plantas, meses, valor, lo, hi):
    """Mapa de calor como tabla HTML: el texto conserva su tamaño en pantallas pequeñas."""
    cab = "<tr><th></th>%s</tr>" % "".join('<th scope="col">%s</th>' % mes_tick(m) for m in meses)
    filas = []
    for cla, nom in plantas:
        celdas = []
        for m in meses:
            f = valor.get((m, cla))
            if f is None:
                celdas.append("<td></td>")
                continue
            q = paso_q(f["costo_flete_por_ton"], lo, hi)
            tip = "%s · %s\nFlete por tonelada|$%s\nToneladas|%s t\nViajes|%s" % (
                nom, mes_largo(m), n2(f["costo_flete_por_ton"]), n1(f["toneladas_embarcadas"]), n0(f["num_viajes"]))
            celdas.append('<td><div class="hm-cell bq%d mark" tabindex="0" data-tip="%s">$%s</div></td>'
                          % (q, esc(tip), n0(f["costo_flete_por_ton"])))
        filas.append('<tr><th scope="row">%s</th>%s</tr>' % (esc(nom), "".join(celdas)))
    return ('<table class="hm" aria-label="Flete por tonelada por planta y mes, entre $%s y $%s">'
            "<thead>%s</thead><tbody>%s</tbody></table>" % (n0(lo), n0(hi), cab, "".join(filas)))


def leyenda_escala(lo, hi):
    pasos = "".join('<span class="sc-step bq%d"></span>' % k for k in range(7))
    return ('<div class="scale" aria-label="Escala de color, de menor a mayor"><span class="sc-lab">$%s/t</span>'
            '<span class="sc-bar">%s</span><span class="sc-lab">$%s/t</span></div>' % (n0(lo), pasos, n0(hi)))


def panel_linea(seg, meses, serie, total, resumen):
    """Línea del segmento (color propio) contra el total del mes (gris), con cruz y tooltip."""
    W, H = 360, 214
    ml, mr, mt, mb = 48, 44, 40, 30
    pw, ph = W - ml - mr, H - mt - mb
    lo, hi = 50.0, 100.0
    n = len(meses)
    step = pw / (n - 1)
    X = lambda i: ml + step * i  # noqa: E731
    Y = lambda v: mt + ph - ph * (v - lo) / (hi - lo)  # noqa: E731
    color = SEG_COLOR[seg]
    p = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Porcentaje de toneladas a tiempo por mes, %s">' % (W, H, esc(SEG_NOMBRE[seg]))]
    p.append('<text x="%d" y="16" class="t-ink t-title">%s</text>' % (ml, esc(SEG_NOMBRE[seg])))
    p.append('<text x="%d" y="16" class="t-sec" text-anchor="end">%s</text>' % (W - mr + 32, esc(resumen)))
    for t in (50, 75, 100):
        p.append('<line x1="%d" x2="%d" y1="%s" y2="%s" class="%s"/>' % (ml, W - mr, c1(Y(t)), c1(Y(t)), "ax" if t == 50 else "gl"))
        p.append('<text x="%d" y="%s" text-anchor="end" class="t-mut">%d %%</text>' % (ml - 8, c1(Y(t) + 4), t))
    tot_pts = ["%s,%s" % (c1(X(i)), c1(Y(total[m]["pct"]))) for i, m in enumerate(meses)]
    p.append('<polyline points="%s" class="ln-total"/>' % " ".join(tot_pts))
    seg_pts = [(i, m) for i, m in enumerate(meses) if m in serie]
    p.append('<polyline points="%s" class="ln" style="stroke:%s"/>'
             % (" ".join("%s,%s" % (c1(X(i)), c1(Y(serie[m]["pct"]))) for i, m in seg_pts), color))
    for i, m in enumerate(meses):
        if m not in serie:
            continue
        p.append('<circle cx="%s" cy="%s" r="4" class="dot" style="fill:%s"/>' % (c1(X(i)), c1(Y(serie[m]["pct"])), color))
    for i, m in enumerate(meses):
        p.append('<text x="%s" y="%d" text-anchor="middle" class="t-mut">%s</text>' % (c1(X(i)), mt + ph + 18, mes_tick(m)))
        s = serie.get(m)
        tip = "%s · %s\n%s|%s %%\nToneladas entregadas|%s t\nTotal del mes|%s %%" % (
            SEG_NOMBRE[seg], mes_largo(m), SEG_NOMBRE[seg], n1(s["pct"]) if s else "—",
            n1(s["ton"]) if s else "0", n1(total[m]["pct"]))
        p.append('<g class="hit" tabindex="0" data-tip="%s"><line class="xh" x1="%s" x2="%s" y1="%d" y2="%d"/>'
                 '<rect x="%s" y="%d" width="%s" height="%d" fill="transparent"/></g>'
                 % (esc(tip), c1(X(i)), c1(X(i)), mt, mt + ph, c1(X(i) - step / 2), mt, c1(step), ph))
    ultimo = [m for m in meses if m in serie][-1]
    p.append('<text x="%s" y="%s" class="t-ink t-val">%s %%</text>'
             % (c1(X(meses.index(ultimo)) + 9), c1(Y(serie[ultimo]["pct"]) + 4), n1(serie[ultimo]["pct"])))
    p.append("</svg>")
    return "".join(p)


# --- bloques HTML -------------------------------------------------------------------------------
def tabla_html(columnas, filas, alinear):
    cab = "".join("<th>%s</th>" % esc(c) for c in columnas)
    cuerpo = "".join("<tr>%s</tr>" % "".join('<td class="%s">%s</td>' % (a, esc(v)) for v, a in zip(f, alinear)) for f in filas)
    return '<div class="tbl-wrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (cab, cuerpo)


def detalle(titulo, contenido):
    return '<details class="twin"><summary>%s</summary>%s</details>' % (esc(titulo), contenido)


def filas_impacto(imp):
    """Cada hallazgo como (id, título, % de desviación del indicador afectado, texto del valor)."""
    def fila(h, k=0):
        return dict(zip(imp[h]["columnas"], imp[h]["filas"][k]))
    h01, h03, h04, h05 = fila("H01"), fila("H03"), fila("H04"), fila("H05")
    h07 = imp["H07"]["filas"]
    h08 = [dict(zip(imp["H08"]["columnas"], r)) for r in imp["H08"]["filas"] if r[0] == 0][0]
    h09 = [dict(zip(imp["H09"]["columnas"], r)) for r in imp["H09"]["filas"]]
    h10, h11, h13, h14, h15, h16 = fila("H10"), fila("H11"), fila("H13"), fila("H14"), fila("H15"), fila("H16")
    h12_t = sum(r[3] for r in imp["H12"]["filas"])
    T, V, F = h01["toneladas_correcto"], h01["viajes_correcto"], h08["costo_correcto"]
    h07_t = sum(r[3] for r in h07)
    h09_t = sum(r["toneladas"] for r in h09)
    pct = lambda a, b: 100.0 * a / b  # noqa: E731
    filas = [
        ("H01", "No quedarse con la última versión de cada viaje", pct(h01["viajes_ingenuo"] - V, V),
         "+%s %% viajes (%s → %s)" % (n1(pct(h01["viajes_ingenuo"] - V, V)), n0(V), n0(h01["viajes_ingenuo"]))),
        ("H08", "Sumar el flete después de unir con las partidas", h08["sobreestimacion_pct"],
         "+%s %% flete (%s → %s M MXN)" % (n1(h08["sobreestimacion_pct"]), n1(F / 1e6), n1(h08["costo_ingenuo"] / 1e6))),
        ("H11", "Comparar timestamps en vez de fechas (a tiempo)", abs(pct(h11["pct_ton_ingenuo"] - h11["pct_ton_correcto"], h11["pct_ton_correcto"])),
         "−%s %% a tiempo (%s → %s %%)" % (n1(abs(pct(h11["pct_ton_ingenuo"] - h11["pct_ton_correcto"], h11["pct_ton_correcto"]))),
                                          n1(h11["pct_ton_correcto"]), n1(h11["pct_ton_ingenuo"]))),
        ("H05", "No limpiar la fecha centinela 1900-01-01", pct(h05["toneladas"], T),
         "%s %% de t (%s t caen en el mes 1900-01)" % (n1(pct(h05["toneladas"], T)), n0(h05["toneladas"]))),
        ("H04", "No normalizar el estatus (ENT, ent, ' ENT')", pct(h04["viajes_perdidos"], V),
         "−%s %% viajes (%s perdidos)" % (n1(pct(h04["viajes_perdidos"], V)), n0(h04["viajes_perdidos"]))),
        ("H14", "No normalizar el texto del segmento", pct(h14["toneladas_con_categoria_falsa"], T),
         "%s %% de t (%s t en una categoría falsa)" % (n1(pct(h14["toneladas_con_categoria_falsa"], T)), n0(h14["toneladas_con_categoria_falsa"]))),
        ("H12", "Usar el segmento actual y no el vigente", pct(h12_t, T),
         "%s %% de t (%s t en el segmento equivocado)" % (n1(pct(h12_t, T)), n0(h12_t))),
        ("H09", "No filtrar viajes programados y cancelados", pct(h09_t, T),
         "+%s %% de t (%s t que nunca salieron)" % (n1(pct(h09_t, T)), n0(h09_t))),
        ("H13", "Descartar clientes que no están en el maestro", pct(h13["toneladas_no_identificado_embarcadas"], T),
         "−%s %% de t (%s t perdidas)" % (n1(pct(h13["toneladas_no_identificado_embarcadas"], T)), n0(h13["toneladas_no_identificado_embarcadas"]))),
        ("H15", "Usar una versión vieja del costo del flete", pct(h15["diferencia_mxn"], F),
         "%s %% del flete (%s mil MXN)" % (n1(pct(h15["diferencia_mxn"], F)), n0(h15["diferencia_mxn"] / 1000))),
        ("H03", "No excluir los viajes borrados en el origen", pct(h03["toneladas"], T),
         "+%s %% de t (%s viajes que ya no existen)" % (n1(pct(h03["toneladas"], T)), n0(h03["viajes"]))),
        ("H07", "Elegir la fecha final en vez de la real", pct(h07_t, T),
         "%s %% de t (%s t en el mes equivocado)" % (n2(pct(h07_t, T)), n0(h07_t))),
        ("H10", "Quedarse con la primera versión del POD", abs(pct(h10["pct_primera_version"] - h10["pct_correcto"], h10["pct_correcto"])),
         "%s %% a tiempo (%s viajes cambian)" % (n2(abs(pct(h10["pct_primera_version"] - h10["pct_correcto"], h10["pct_correcto"]))),
                                                 n0(h10["corrigen_la_clasificacion"]))),
        ("H16", "Usar una versión vieja del peso de las partidas", pct(h16["diferencia_ton"], T),
         "<0.01 %% de t (%s t)" % n1(h16["diferencia_ton"])),
    ]
    return sorted(filas, key=lambda f: -f[2])


# --- ensamblado ---------------------------------------------------------------------------------
def construir(d):
    emb, cum, imp, emb_d = d["emb"], d["cum"], d["impacto"], d["embudo"]
    meses = sorted({f["anio_mes"] for f in emb})
    plantas = sorted({(f["cla_planta"], f["nom_planta"]) for f in emb})
    por_mp = {(f["anio_mes"], f["cla_planta"]): f for f in emb}

    # --- totales y mensuales -------------------------------------------------------------------
    viajes = sum(f["num_viajes"] for f in emb)
    ton = sum(f["toneladas_embarcadas"] for f in emb)
    flete = sum(f["costo_flete_mxn"] for f in emb)
    entreg = sum(f["toneladas_entregadas"] for f in cum)
    atiempo = sum(f["toneladas_a_tiempo"] for f in cum)
    noid_t = sum(f["toneladas_entregadas"] for f in cum if f["segmento_cliente"] == "NO_IDENTIFICADO")
    pct_global = 100.0 * atiempo / entreg
    m_viajes = [sum(f["num_viajes"] for f in emb if f["anio_mes"] == m) for m in meses]
    m_ton = [sum(f["toneladas_embarcadas"] for f in emb if f["anio_mes"] == m) for m in meses]
    m_flete = [sum(f["costo_flete_mxn"] for f in emb if f["anio_mes"] == m) for m in meses]
    m_cpt = [a / b for a, b in zip(m_flete, m_ton)]
    m_noid = [sum(f["toneladas_entregadas"] for f in cum if f["anio_mes"] == m and f["segmento_cliente"] == "NO_IDENTIFICADO") for m in meses]

    total_mes = {}
    for m in meses:
        e = sum(f["toneladas_entregadas"] for f in cum if f["anio_mes"] == m)
        a = sum(f["toneladas_a_tiempo"] for f in cum if f["anio_mes"] == m)
        total_mes[m] = {"pct": 100.0 * a / e, "ton": e}
    serie_seg = {s: {f["anio_mes"]: {"pct": f["pct_a_tiempo"], "ton": f["toneladas_entregadas"]}
                     for f in cum if f["segmento_cliente"] == s} for s in SEGMENTOS}

    periodo = "%s a %s" % (mes_largo(meses[0]), mes_largo(meses[-1]))
    cpt_lo = min(f["costo_flete_por_ton"] for f in emb)
    cpt_hi = max(f["costo_flete_por_ton"] for f in emb)
    cpt_prom = flete / ton
    tons_planta = {cla: sum(f["toneladas_embarcadas"] for f in emb if f["cla_planta"] == cla) for cla, _ in plantas}
    top = max(plantas, key=lambda p: tons_planta[p[0]])
    mejor = max(meses, key=lambda m: total_mes[m]["pct"])
    peor = min(meses, key=lambda m: total_mes[m]["pct"])
    seg_pct = {s: 100.0 * sum(f["toneladas_a_tiempo"] for f in cum if f["segmento_cliente"] == s)
               / sum(f["toneladas_entregadas"] for f in cum if f["segmento_cliente"] == s) for s in SEGMENTOS}

    # --- KPI ----------------------------------------------------------------------------------
    def tile(etiqueta, valor, sub, valores):
        return ('<div class="tile"><div class="lab">%s</div><div class="val">%s</div><div class="sub">%s</div>%s</div>'
                % (esc(etiqueta), esc(valor), esc(sub), sparkline(valores)))
    tarde = entreg - atiempo
    hero = ('<div class="hero"><div class="lab">Toneladas entregadas a tiempo</div>'
            '<div class="hero-num">%s<span class="hero-unit"> %%</span></div>'
            '<div class="seg-bar" role="img" aria-label="%s t a tiempo y %s t tarde"><span style="width:%s%%;background:var(--s1)"></span>'
            '<span style="width:%s%%;background:var(--axis)"></span></div>'
            '<div class="hero-sub"><span class="key key-fill" style="background:var(--s1)"></span>A tiempo <b>%s t</b>'
            '<span class="key key-fill" style="background:var(--axis)"></span>Tarde <b>%s t</b></div>'
            '<div class="hero-foot">Sobre %s t entregadas con comprobante (POD), por mes de embarque, %s.</div></div>'
            % (n1(pct_global), n0(atiempo), n0(tarde), c1(pct_global), c1(100 - pct_global), n0(atiempo), n0(tarde), n0(entreg), esc(periodo)))
    tiles = "".join([
        tile("Viajes embarcados", n0(viajes), "%s a %s por mes" % (n0(min(m_viajes)), n0(max(m_viajes))), m_viajes),
        tile("Toneladas embarcadas", n0(ton) + " t", "%s a %s t por mes" % (n0(min(m_ton)), n0(max(m_ton))), m_ton),
        tile("Flete total", "$%s M" % n1(flete / 1e6), "MXN, un monto por viaje", m_flete),
        tile("Flete por tonelada", "$%s" % n0(cpt_prom), "MXN/t, de $%s a $%s por mes" % (n0(min(m_cpt)), n0(max(m_cpt))), m_cpt),
        tile("Sin segmento identificado", "%s t" % n0(noid_t), "%s %% de lo entregado" % n1(100.0 * noid_t / entreg), m_noid),
    ])

    # --- embarques ----------------------------------------------------------------------------
    ymax = maximo_agradable(max(f["toneladas_embarcadas"] for f in emb))
    paneles_t = "".join('<div class="panel">%s</div>' % panel_toneladas(
        nom, [por_mp[(m, cla)] for m in meses if (m, cla) in por_mp], ymax, tons_planta[cla]) for cla, nom in plantas)
    calor = mapa_calor(plantas, meses, por_mp, cpt_lo, cpt_hi)
    tabla_emb = detalle("Ver la tabla embarques_mensual (24 filas)", tabla_html(
        ["Mes", "Planta", "Viajes", "Toneladas", "Flete MXN", "Flete por t"],
        [(f["anio_mes"], f["nom_planta"], n0(f["num_viajes"]), n1(f["toneladas_embarcadas"]), n2(f["costo_flete_mxn"]),
          n2(f["costo_flete_por_ton"])) for f in emb], ["", "", "num", "num", "num", "num"]))
    lead_emb = ("%s concentra %s %% de las toneladas del semestre. El flete por tonelada es muy estable: va de $%s a $%s "
                "(±%s %% alrededor de $%s), así que las diferencias entre plantas y meses son pequeñas."
                % (top[1], n0(100.0 * tons_planta[top[0]] / ton), n0(cpt_lo), n0(cpt_hi),
                   n1(100.0 * (cpt_hi - cpt_lo) / 2 / cpt_prom), n0(cpt_prom)))

    # --- cumplimiento -------------------------------------------------------------------------
    paneles_c = "".join('<div class="panel">%s</div>' % panel_linea(
        s, meses, serie_seg[s], total_mes, "%s %% en el semestre" % n1(seg_pct[s])) for s in SEGMENTOS)
    tabla_cum = detalle("Ver la tabla cumplimiento_entrega (24 filas)", tabla_html(
        ["Mes", "Segmento", "Toneladas entregadas", "Toneladas a tiempo", "% a tiempo"],
        [(f["anio_mes"], SEG_NOMBRE[f["segmento_cliente"]], n1(f["toneladas_entregadas"]), n1(f["toneladas_a_tiempo"]),
          n2(f["pct_a_tiempo"])) for f in cum], ["", "", "num", "num", "num"]))
    lead_cum = ("El cumplimiento global fue %s %%; el mejor mes de embarque fue %s (%s %%) y el más bajo %s (%s %%). "
                "Cada recuadro compara un segmento (color) con el total del mes (gris). «No identificado» son clientes que no "
                "existen en el maestro: pesa solo %s %% de lo entregado, por eso sus meses son muy variables."
                % (n1(pct_global), mes_largo(mejor), n1(total_mes[mejor]["pct"]), mes_largo(peor), n1(total_mes[peor]["pct"]),
                   n1(100.0 * noid_t / entreg)))

    # --- calidad: embudo, impacto, matriz -------------------------------------------------------
    etapas = [
        ("Filas replicadas (todas las versiones)", emb_d["filas"], "filas, una por cada versión de un viaje"),
        ("Viajes únicos", emb_d["unicos"], "−%s versiones anteriores y copias exactas" % n0(emb_d["filas"] - emb_d["unicos"])),
        ("Viajes vigentes", emb_d["vigentes"], "−%s borrados en el origen" % n0(emb_d["unicos"] - emb_d["vigentes"])),
        ("Viajes embarcados (TRA o ENT)", emb_d["embarcados"], "−%s programados (PRO) o cancelados (CAN)" % n0(emb_d["vigentes"] - emb_d["embarcados"])),
        ("Embarcados con comprobante de entrega", emb_d["con_pod"], "−%s sin POD: no se pueden evaluar" % n0(emb_d["embarcados"] - emb_d["con_pod"])),
    ]
    mx = etapas[0][1]
    embudo = "".join(
        '<div class="fn-row"><div class="fn-lab"><b>%s</b><span>%s</span></div>'
        '<div class="fn-track"><span class="fn-bar mark" tabindex="0" style="width:%s%%;background:var(--o%d)" data-tip="%s"></span></div>'
        '<div class="fn-val">%s</div></div>'
        % (esc(nom), esc(sub), c1(max(1.0, 100.0 * v / mx)), i, esc("%s\n%s|%s" % (nom, "Cantidad", n0(v))), n0(v))
        for i, (nom, v, sub) in enumerate(etapas))

    ranking = filas_impacto(imp)
    mx_i = max(f[2] for f in ranking)
    filas_rk = "".join(
        '<div class="rk-row"><div class="rk-lab"><span class="rk-id">%s</span>%s</div>'
        '<div class="rk-track"><span class="rk-bar mark" tabindex="0" style="width:%s%%" data-tip="%s"></span></div>'
        '<div class="rk-val">%s</div></div>'
        % (hid, esc(tit), c1(max(0.6, 100.0 * pct / mx_i)), esc("%s · %s\n%s" % (hid, tit, txt.replace(" (", "\n(", 1))), esc(txt))
        for hid, tit, pct, txt in ranking)

    h12 = {(r[0], r[1]): (r[2], r[3]) for r in imp["H12"]["filas"]}
    valores_h12 = [v[1] for v in h12.values()]
    lo12, hi12 = min(valores_h12), max(valores_h12)
    celdas = ['<div class="mx-corner"></div>'] + ['<div class="mx-colh">%s</div>' % esc(SEG_NOMBRE[s]) for s in SEGMENTOS[:3]]
    for fila_s in SEGMENTOS[:3]:
        celdas.append('<div class="mx-rowh">%s</div>' % esc(SEG_NOMBRE[fila_s]))
        for col_s in SEGMENTOS[:3]:
            if fila_s == col_s:
                celdas.append('<div class="mx-cell mx-diag" aria-label="sin cambio">—</div>')
                continue
            par = h12.get((fila_s, col_s))
            if not par:
                celdas.append('<div class="mx-cell mx-diag">0</div>')
                continue
            q = paso_q(par[1], lo12, hi12)
            tip = "Segmento correcto: %s\nSi se usara el actual: %s\nToneladas|%s t\nPartidas|%s" % (
                SEG_NOMBRE[fila_s], SEG_NOMBRE[col_s], n1(par[1]), n0(par[0]))
            celdas.append('<div class="mx-cell bq%d mark" tabindex="0" data-tip="%s"><b>%s</b><span>t</span></div>' % (q, esc(tip), n0(par[1])))
    total_h12 = sum(valores_h12)
    matriz = '<div class="mx" role="table" aria-label="Toneladas que cambiarían de segmento">%s</div>' % "".join(celdas)

    tabla_imp = detalle("Ver la tabla de impacto de los 14 hallazgos principales", tabla_html(
        ["Hallazgo", "Qué pasa si se ignora", "Efecto"],
        [(hid, tit, txt) for hid, tit, _, txt in ranking], ["", "", ""]))

    # --- documento ------------------------------------------------------------------------------
    css = CSS.replace("/*CLARO*/", _vars(CLARO)).replace("/*OSCURO*/", _vars(OSCURO))
    cuerpo = """
<header class="top">
  <div><p class="eyebrow">Dirección de Logística · Grupo DEACERO (datos ficticios del reto)</p>
  <h1>Desempeño de embarques</h1>
  <p class="lead">%(periodo)s · cuatro plantas · fuente: <code>mart_logistica</code> (<code>embarques_mensual</code> y <code>cumplimiento_entrega</code>)</p></div>
  <button id="theme" class="btn" type="button" aria-label="Cambiar entre tema claro y oscuro">Tema</button>
</header>

<section class="kpis" aria-label="Indicadores principales">
  <div class="card hero-card">%(hero)s</div>
  <div class="tiles">%(tiles)s</div>
</section>

<section class="card" id="embarques">
  <h2>Embarques por planta</h2>
  <p class="lead">%(lead_emb)s</p>
  <h3>Toneladas embarcadas por mes</h3>
  <div class="grid2">%(paneles_t)s</div>
  <h3>Flete por tonelada (MXN/t)</h3>
  <p class="note">Cada celda es un mes y una planta. Los valores están en un rango muy estrecho, así que el color sirve para ubicar los extremos: lee siempre la cifra de la celda y la escala de abajo (de menor a mayor).</p>
  <div class="heat">%(calor)s</div>
  %(escala)s
  %(tabla_emb)s
</section>

<section class="card" id="cumplimiento">
  <h2>Cumplimiento de entrega por segmento de cliente</h2>
  <p class="lead">%(lead_cum)s</p>
  <div class="legend" aria-label="Leyenda"><span class="lg"><svg width="24" height="8" aria-hidden="true"><line x1="0" x2="24" y1="4" y2="4" class="ln" style="stroke:var(--ink2)"/></svg>Segmento</span>
  <span class="lg"><svg width="24" height="8" aria-hidden="true"><line x1="0" x2="24" y1="4" y2="4" class="ln-total"/></svg>Total del mes (todos los segmentos)</span>
  <span class="lg-note">Eje vertical de 50 %% a 100 %%</span></div>
  <div class="grid2">%(paneles_c)s</div>
  %(tabla_cum)s
</section>

<section class="card" id="calidad">
  <h2>Calidad de los datos: qué costó llegar a estas cifras</h2>
  <p class="lead">Los datos llegan como historia de versiones, con borrados, texto sucio y fechas centinela. Dos vistas del trabajo de limpieza:
  cuánto se reduce el dato crudo hasta los viajes que cuentan, y cuánto se equivocaría cada indicador si se ignorara cada problema
  (detalle de los 19 hallazgos en <a href="../HALLAZGOS.md">HALLAZGOS.md</a>).</p>
  <h3>De la réplica a los viajes que cuentan</h3>
  <div class="funnel">%(embudo)s</div>
  <h3>Cuánto cambiaría el resultado si se ignorara cada problema</h3>
  <p class="note">Barra = desviación relativa del indicador afectado (flete, viajes, toneladas o %% a tiempo, según el caso). Calculado con <code>tools/analisis_impacto.py</code>.</p>
  <div class="ranked">%(filas_rk)s</div>
  %(tabla_imp)s
  <h3>Toneladas que cambiarían de segmento si se usara el segmento actual</h3>
  <p class="note">13 clientes cambian de segmento durante el año. Filas: segmento correcto el día del embarque. Columnas: segmento que recibirían con el segmento actual. En total %(total_h12)s t (%(pct_h12)s %% de lo embarcado).</p>
  %(matriz)s
</section>

<footer class="foot">
  <p>Generado por <code>python tools/generar_dashboard.py</code> a partir de <code>deacero.duckdb</code> y <code>reporte/impacto_hallazgos.json</code>; el CI comprueba que este archivo no quede desactualizado.
  Paleta categórica y secuencial validada con el validador de contraste y daltonismo del skill de visualización (modo claro y oscuro).</p>
</footer>
<div id="tip" role="tooltip" hidden></div>
""" % {"periodo": esc(periodo), "hero": hero, "tiles": tiles, "lead_emb": esc(lead_emb), "paneles_t": paneles_t, "calor": calor,
       "escala": leyenda_escala(cpt_lo, cpt_hi), "tabla_emb": tabla_emb, "lead_cum": esc(lead_cum),
       "paneles_c": paneles_c, "tabla_cum": tabla_cum, "embudo": embudo, "filas_rk": filas_rk, "tabla_imp": tabla_imp,
       "matriz": matriz, "total_h12": n0(total_h12),
       "pct_h12": n1(100.0 * total_h12 / ton)}
    return ('<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>Desempeño de embarques</title>\n<style>%s</style>\n</head>\n<body>\n<div class="wrap">%s</div>\n'
            '<script>%s</script>\n</body>\n</html>\n' % (css, cuerpo, JS))


def _vars(p):
    v = ["--page:%s" % p["page"], "--surface:%s" % p["surface"], "--ink:%s" % p["ink"], "--ink2:%s" % p["ink2"],
         "--muted:%s" % p["muted"], "--grid:%s" % p["grid"], "--axis:%s" % p["axis"], "--border:%s" % p["border"],
         "--good:%s" % p["good"], "--s1:%s" % p["s1"], "--s2:%s" % p["s2"], "--s3:%s" % p["s3"]]
    for k, col in enumerate(p["q"]):
        v += ["--q%d:%s" % (k, col), "--qi%d:%s" % (k, tinta_sobre(col))]
    for k, col in enumerate(p["o"]):
        v.append("--o%d:%s" % (k, col))
    return ";".join(v) + ";"


CSS = """
:root{color-scheme:light;/*CLARO*/}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;/*OSCURO*/}}
:root[data-theme="dark"]{color-scheme:dark;/*OSCURO*/}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.45}
.wrap{max-width:1120px;margin:0 auto;padding:24px 16px 56px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:var(--grid);padding:1px 5px;border-radius:4px}
a{color:var(--s1)}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:16px}
.eyebrow{margin:0 0 4px;color:var(--ink2);font-size:13px}
h1{margin:0;font-size:28px;font-weight:650;letter-spacing:-.01em}
h2{margin:0 0 6px;font-size:20px;font-weight:650}
h3{margin:24px 0 8px;font-size:15px;font-weight:650}
.lead{margin:6px 0 0;color:var(--ink2);font-size:14px;max-width:80ch}
.note{margin:0 0 8px;color:var(--muted);font-size:13px;max-width:80ch}
.btn{font:inherit;font-size:13px;color:var(--ink);background:var(--surface);border:1px solid var(--axis);border-radius:8px;padding:6px 12px;cursor:pointer}
.btn:hover{background:var(--grid)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin-top:16px}
.kpis{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1.6fr);gap:16px;align-items:stretch}
.kpis .card{margin-top:0}
@media (max-width:860px){.kpis{grid-template-columns:1fr}}
.hero-card{display:flex;align-items:center}
.hero .lab{color:var(--ink2);font-size:14px}
.hero-num{font-size:68px;line-height:1.05;font-weight:600;letter-spacing:-.02em;margin:2px 0 10px}
.hero-unit{font-size:34px;color:var(--ink2);font-weight:500}
.seg-bar{display:flex;gap:2px;height:8px;border-radius:4px;overflow:hidden;margin:4px 0 10px}
.seg-bar span{display:block;height:100%}
.hero-sub{display:flex;flex-wrap:wrap;gap:4px 16px;align-items:center;font-size:14px;color:var(--ink2)}
.hero-sub b{color:var(--ink);font-weight:600}
.key{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
.hero-foot{margin-top:10px;color:var(--muted);font-size:12.5px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px;display:flex;flex-direction:column}
.tile .lab{color:var(--ink2);font-size:13px}
.tile .val{font-size:26px;font-weight:600;margin:2px 0}
.tile .sub{color:var(--muted);font-size:12px;margin-bottom:6px;min-height:2.6em}
.spark{width:100%;max-width:130px;height:auto;margin-top:auto}
.sp-line{fill:none;stroke:var(--muted);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.sp-dot{fill:var(--s1);stroke:var(--surface);stroke-width:2}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 20px}
@media (max-width:760px){.grid2{grid-template-columns:1fr}}
.panel{min-width:0}
svg{width:100%;height:auto;display:block;overflow:visible}
svg text{font-family:inherit;font-size:11.5px;fill:var(--ink2)}
.t-ink{fill:var(--ink)} .t-sec{fill:var(--ink2)} .t-mut{fill:var(--muted)}
.t-title{font-size:13px;font-weight:600} .t-val{font-weight:600}
.gl{stroke:var(--grid);stroke-width:1} .ax{stroke:var(--axis);stroke-width:1}
.bar{fill:var(--s1)}
.mark{outline:none;cursor:default}
.mark:hover .bar,.mark:focus .bar{opacity:.78}
.mark:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.hit{outline:none}
.xh{stroke:var(--axis);stroke-width:1;opacity:0}
.hit:hover .xh,.hit:focus .xh{opacity:1}
.ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.ln-total{fill:none;stroke:var(--muted);stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}
.dot{stroke:var(--surface);stroke-width:2}
.heat{max-width:760px}
.hm{border-collapse:separate;border-spacing:2px;width:100%;table-layout:fixed}
.hm th,.hm td{padding:0;border:0;white-space:normal}
.hm thead th{font-weight:400;color:var(--muted);font-size:12px;text-align:center;padding-bottom:2px}
.hm thead th:first-child{width:132px}
.hm tbody th{text-align:right;font-weight:400;font-size:13px;color:var(--ink);padding-right:10px}
.hm-cell{border-radius:4px;padding:11px 0;text-align:center;font-weight:600;font-size:13px}
.hm-cell:hover,.hm-cell:focus{outline:2px solid var(--ink);outline-offset:-2px}
.bq0{background:var(--q0);color:var(--qi0)}\n.bq1{background:var(--q1);color:var(--qi1)}\n.bq2{background:var(--q2);color:var(--qi2)}\n.bq3{background:var(--q3);color:var(--qi3)}\n.bq4{background:var(--q4);color:var(--qi4)}\n.bq5{background:var(--q5);color:var(--qi5)}\n.bq6{background:var(--q6);color:var(--qi6)}\n.scale{display:flex;align-items:center;gap:8px;margin:10px 0 4px 144px;max-width:560px;font-size:12px;color:var(--ink2)}
.sc-bar{display:flex;flex:1;max-width:320px}
.sc-step{flex:1;height:10px;display:block}
.sc-step:first-child{border-radius:4px 0 0 4px}.sc-step:last-child{border-radius:0 4px 4px 0}
.legend{display:flex;flex-wrap:wrap;gap:6px 20px;align-items:center;margin:12px 0 4px;font-size:13px;color:var(--ink2)}
.lg{display:inline-flex;align-items:center;gap:8px}
.lg svg{width:24px;height:8px;flex:none;display:inline-block}
.lg-note{color:var(--muted)}
.funnel,.ranked{margin-top:6px}
.fn-row{display:grid;grid-template-columns:minmax(180px,1.1fr) minmax(80px,1.6fr) 64px;gap:12px;align-items:center;padding:8px 0;border-top:1px solid var(--grid)}
.fn-lab b{display:block;font-weight:600;font-size:14px}
.fn-lab span{display:block;color:var(--muted);font-size:12.5px}
.fn-track,.rk-track{height:14px}
.fn-bar,.rk-bar{display:block;height:14px;border-radius:0 4px 4px 0}
.fn-val,.rk-val{font-size:14px;font-weight:600}
.fn-val{text-align:right}
.rk-row{display:grid;grid-template-columns:minmax(220px,1.3fr) minmax(80px,1.2fr) minmax(190px,1.2fr);gap:12px;align-items:center;padding:7px 0;border-top:1px solid var(--grid)}
.rk-lab{font-size:14px}
.rk-id{display:inline-block;min-width:2.8em;color:var(--muted);font-size:12px;font-weight:600}
.rk-bar{background:var(--s1);height:10px}
.rk-track{height:10px}
.rk-val{font-weight:500;font-size:13px;color:var(--ink2)}
@media (max-width:760px){.fn-row{grid-template-columns:1fr 56px}.fn-track{grid-column:1/3;grid-row:2}.rk-row{grid-template-columns:1fr}.rk-val{font-size:12.5px}}
.mark.fn-bar:hover,.mark.rk-bar:hover,.mark.fn-bar:focus,.mark.rk-bar:focus{opacity:.8}
.mx{display:grid;grid-template-columns:130px repeat(3,minmax(0,1fr));gap:2px;max-width:640px;margin-top:6px}
.mx-colh{padding:4px 8px;font-size:12.5px;color:var(--ink2);text-align:center}
.mx-rowh{padding:10px 8px 10px 0;font-size:13px;color:var(--ink2);text-align:right;align-self:center}
.mx-cell{border-radius:4px;padding:12px 8px;text-align:center;display:flex;gap:4px;align-items:baseline;justify-content:center}
.mx-cell b{font-size:15px;font-weight:600}.mx-cell span{font-size:11px;opacity:.85}
.mx-diag{background:transparent;color:var(--muted);border:1px solid var(--grid)}
.twin{margin-top:14px;font-size:13px}
.twin summary{cursor:pointer;color:var(--ink2);padding:4px 0}
.tbl-wrap{overflow-x:auto;margin-top:6px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:6px 10px;border-top:1px solid var(--grid);text-align:left;white-space:nowrap}
th{color:var(--ink2);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.foot{margin-top:24px;color:var(--muted);font-size:12.5px;max-width:90ch}
#tip{position:fixed;z-index:20;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--axis);border-radius:8px;padding:8px 10px;font-size:12.5px;box-shadow:0 6px 20px rgba(0,0,0,.18);max-width:280px}
#tip[hidden]{display:none}
.tip-h{font-weight:600;margin-bottom:4px}
.tip-r{display:flex;justify-content:space-between;gap:14px}
.tip-r span{color:var(--ink2)} .tip-r b{font-weight:600}
@media (max-width:760px){.scale{margin-left:0}.hm thead th:first-child{width:76px}.hm tbody th{font-size:11.5px;padding-right:6px}.hm-cell{font-size:11.5px;padding:9px 0}.mx{grid-template-columns:84px repeat(3,minmax(0,1fr))}.mx-colh{font-size:11.5px;padding:4px 1px}.mx-rowh{font-size:12px;padding-right:6px}}
@media (forced-colors:active){.bar,.fn-bar,.rk-bar{forced-color-adjust:none}}
"""

JS = r"""
(function () {
  var tip = document.getElementById('tip');
  function render(raw) {
    tip.textContent = '';
    raw.split('\n').forEach(function (line, i) {
      var row = document.createElement('div');
      if (i === 0) { row.className = 'tip-h'; row.textContent = line; }
      else {
        row.className = 'tip-r';
        var parts = line.split('|');
        var a = document.createElement('span'); a.textContent = parts[0];
        row.appendChild(a);
        if (parts.length > 1) { var b = document.createElement('b'); b.textContent = parts[1]; row.appendChild(b); }
      }
      tip.appendChild(row);
    });
  }
  function place(x, y) {
    tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    var left = x + 14, top = y + 14;
    if (left + w > vw - 8) left = x - w - 14;
    if (top + h > vh - 8) top = y - h - 14;
    tip.style.left = Math.max(8, left) + 'px';
    tip.style.top = Math.max(8, top) + 'px';
  }
  function target(el) { return el && el.closest ? el.closest('[data-tip]') : null; }
  document.addEventListener('pointermove', function (e) {
    var t = target(e.target);
    if (t) { render(t.getAttribute('data-tip')); place(e.clientX, e.clientY); } else { tip.hidden = true; }
  });
  document.addEventListener('pointerleave', function () { tip.hidden = true; });
  document.addEventListener('focusin', function (e) {
    var t = target(e.target);
    if (t) { var r = t.getBoundingClientRect(); render(t.getAttribute('data-tip')); place(r.left + r.width / 2, r.top); }
  });
  document.addEventListener('focusout', function () { tip.hidden = true; });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') tip.hidden = true; });

  var root = document.documentElement, btn = document.getElementById('theme');
  function efectivo() {
    var t = root.getAttribute('data-theme');
    if (t) return t;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  try { var g = localStorage.getItem('tema'); if (g === 'dark' || g === 'light') root.setAttribute('data-theme', g); } catch (err) {}
  btn.addEventListener('click', function () {
    var n = efectivo() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', n);
    try { localStorage.setItem('tema', n); } catch (err) {}
  });
})();
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(RAIZ / "deacero.duckdb"))
    ap.add_argument("--impacto", default=str(RAIZ / "reporte" / "impacto_hallazgos.json"))
    ap.add_argument("--salida", default=str(RAIZ / "reporte" / "dashboard.html"))
    args = ap.parse_args()
    for ruta in (args.db, args.impacto):
        if not Path(ruta).exists():
            print("No existe %s. Corre antes `dbt build` y `python tools/analisis_impacto.py`." % ruta, file=sys.stderr)
            return 2
    documento = construir(cargar(args.db, args.impacto))
    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(documento, encoding="utf-8")
    print("Dashboard escrito en %s (%d KB)" % (salida, len(documento.encode("utf-8")) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
