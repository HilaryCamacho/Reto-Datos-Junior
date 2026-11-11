"""Análisis de impacto de los hallazgos de calidad de datos.

Para cada problema encontrado en la réplica, compara el resultado CORRECTO (el del proyecto)
contra el resultado INGENUO (el que saldría si el problema se ignorara). Es la base cuantitativa
de HALLAZGOS.md: "cómo afecta al resultado" con números reproducibles, no con opiniones.

Requiere haber corrido antes `dbt build` (lee deacero.duckdb en modo solo lectura).

Uso (desde la raíz del repo, con el entorno virtual activo):
    python tools/analisis_impacto.py                  # imprime Markdown y escribe el JSON
    python tools/analisis_impacto.py --sin-json
"""
import argparse
import decimal
import json
import sys
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent.parent

# Vistas auxiliares (solo en memoria de esta conexión). Parten de landing, en crudo.
PREPARACION = [
    # Última versión de cada viaje, INCLUYENDO las filas de borrado (columna del).
    """create temp view vu as
       select cast(IdViaje as integer) id_viaje, cast(ClaPlanta as integer) cla_planta,
              Estatus est_raw, upper(trim(Estatus)) est,
              FechaRealEmbarque real_txt, FechaEmbarqueFinal final_txt,
              cast(CostoFlete as decimal(18,2)) costo, _ab_cdc_deleted_at del
       from (select *, row_number() over (partition by IdViaje
                       order by cast(_ab_cdc_lsn as bigint) desc, _airbyte_extracted_at desc) rn
             from landing_fle.fle_viaje) where rn = 1""",
    # Última versión de cada partida (vigentes).
    """create temp view du as
       select cast(IdViaje as integer) id_viaje, cast(IdPartida as integer) id_partida,
              cast(ClaCliente as integer) cla_cliente, cast(PesoKg as decimal(18,3)) kg
       from (select *, row_number() over (partition by IdViaje, IdPartida
                       order by cast(_ab_cdc_lsn as bigint) desc, _airbyte_extracted_at desc) rn
             from landing_fle.fle_viaje_det) where rn = 1 and _ab_cdc_deleted_at is null""",
    "create temp view kgv as select id_viaje, sum(kg) kg, count(*) n from du group by id_viaje",
]

TRA_ENT = "('TRA','ENT')"

# (id, título, qué compara, SQL). Cada SQL devuelve una o varias filas con columnas legibles.
HALLAZGOS = [
    ("H01", "Versiones CDC: la tabla trae historia, no el estado actual",
     "Sin quedarse con la última versión, viajes y toneladas se inflan.",
     f"""select
           (select count(*) from gold_logistica.fct_embarques) as viajes_correcto,
           (select count(*) from landing_fle.fle_viaje where upper(trim(Estatus)) in {TRA_ENT}) as viajes_ingenuo,
           (select round(sum(toneladas),3) from gold_logistica.fct_embarques) as toneladas_correcto,
           (select round(sum(cast(PesoKg as double))/1000,3) from landing_fle.fle_viaje_det
             where IdViaje in (select IdViaje from landing_fle.fle_viaje
                               where upper(trim(Estatus)) in {TRA_ENT})) as toneladas_ingenuo"""),

    ("H02", "Filas duplicadas exactas de Airbyte (mismo LSN, mismo contenido)",
     "Copias idénticas que no son versiones nuevas.",
     """select 'fle_viaje' tabla, count(*) filas,
               (select count(*) from (select distinct * exclude(_archivo_origen) from landing_fle.fle_viaje)) filas_distintas from landing_fle.fle_viaje
        union all select 'fle_viaje_det', count(*),
               (select count(*) from (select distinct * exclude(_archivo_origen) from landing_fle.fle_viaje_det)) from landing_fle.fle_viaje_det
        union all select 'fle_entrega', count(*),
               (select count(*) from (select distinct * exclude(_archivo_origen) from landing_fle.fle_entrega)) from landing_fle.fle_entrega
        union all select 'vta_cliente', count(*),
               (select count(*) from (select distinct * exclude(_archivo_origen) from landing_vta.vta_cliente)) from landing_vta.vta_cliente"""),

    ("H03", "Viajes borrados en el origen que aún traen estatus TRA/ENT",
     "Si no se excluyen, se cuentan viajes que ya no existen.",
     f"""select count(*) viajes, round(sum(k.kg)/1000,3) toneladas, round(sum(v.costo),2) costo_mxn
        from vu v join kgv k using(id_viaje)
        where v.del is not null and v.est in {TRA_ENT}"""),

    ("H04", "Estatus con mayúsculas y espacios mezclados (ENT, Ent, ' ENT', 'ent ')",
     "Filtrar con IN ('TRA','ENT') sin normalizar pierde viajes embarcados.",
     f"""select count(*) viajes_perdidos, round(sum(k.kg)/1000,3) toneladas_perdidas, round(sum(v.costo),2) costo_perdido_mxn,
               (select count(*) from gold_logistica.fct_embarques) viajes_correcto
        from vu v join kgv k using(id_viaje)
        where v.del is null and v.est in {TRA_ENT} and v.est_raw not in {TRA_ENT}"""),

    ("H05", "Fecha centinela 1900-01-01 en FechaRealEmbarque de viajes embarcados",
     "Sin limpiarla el viaje se agrupa en el mes '1900-01' y desaparece de su mes real.",
     f"""select count(*) viajes, round(sum(k.kg)/1000,3) toneladas, round(sum(v.costo),2) costo_mxn
        from vu v join kgv k using(id_viaje)
        where v.del is null and v.est in {TRA_ENT} and v.real_txt like '1900%'"""),

    ("H06", "Viajes embarcados sin fecha real válida: dependen del respaldo FechaEmbarqueFinal",
     "Usar solo FechaRealEmbarque dejaría estos viajes sin mes.",
     f"""select case when v.real_txt is null then 'real NULL' else 'real 1900-01-01' end causa,
               count(*) viajes, round(sum(k.kg)/1000,3) toneladas, round(sum(v.costo),2) costo_mxn
        from vu v join kgv k using(id_viaje)
        where v.del is null and v.est in {TRA_ENT} and (v.real_txt is null or v.real_txt like '1900%')
        group by 1 order by 1"""),

    ("H07", "Fecha real y fecha final caen en meses distintos",
     "Elegir la fecha final mueve estos viajes de mes.",
     f"""select substr(v.real_txt,1,7) mes_correcto, substr(v.final_txt,1,7) mes_si_usa_fecha_final,
               count(*) viajes, round(sum(k.kg)/1000,3) toneladas
        from vu v join kgv k using(id_viaje)
        where v.del is null and v.est in {TRA_ENT} and v.real_txt is not null and v.real_txt not like '1900%'
          and substr(v.real_txt,1,7) <> substr(v.final_txt,1,7)
        group by 1,2 order by 1"""),

    ("H08", "El flete es por viaje pero el viaje tiene varias partidas",
     "Unir con partidas y sumar el costo lo multiplica por el número de partidas.",
     """select cla_planta,
               round(sum(costo_flete_mxn),2) costo_correcto,
               round(sum(costo_flete_mxn * num_partidas),2) costo_ingenuo,
               round(100.0*(sum(costo_flete_mxn * num_partidas)/sum(costo_flete_mxn)-1),1) sobreestimacion_pct
        from gold_logistica.fct_embarques group by 1
        union all
        select 0, round(sum(costo_flete_mxn),2), round(sum(costo_flete_mxn * num_partidas),2),
               round(100.0*(sum(costo_flete_mxn * num_partidas)/sum(costo_flete_mxn)-1),1)
        from gold_logistica.fct_embarques order by 1"""),

    ("H09", "Viajes PRO y CAN traen partidas con peso",
     "Si no se filtra por estatus, se cuentan toneladas que nunca salieron.",
     """select v.est estatus, count(*) viajes, round(sum(k.kg)/1000,3) toneladas
        from vu v join kgv k using(id_viaje)
        where v.del is null and v.est in ('PRO','CAN') group by 1 order by 1"""),

    ("H10", "Tráfico corrige la fecha del POD (hay varias versiones)",
     "Quedarse con la primera versión cambia la puntualidad de algunos viajes.",
     """with primera as (
            select cast(IdViaje as integer) id_viaje, cast(substr(FechaEntrega,1,10) as date) f
            from (select *, row_number() over (partition by IdViaje order by cast(_ab_cdc_lsn as bigint) asc,
                                               _airbyte_extracted_at asc) rn from landing_fle.fle_entrega) where rn = 1)
        select count(*) filter (where pr.f <> p.fecha_entrega) pods_corregidos,
               count(*) filter (where (pr.f <= p.fecha_compromiso) <> p.a_tiempo) corrigen_la_clasificacion,
               round(sum(case when p.a_tiempo then f.toneladas else 0 end),3) ton_a_tiempo_correcto,
               round(sum(case when pr.f <= p.fecha_compromiso then f.toneladas else 0 end),3) ton_a_tiempo_primera_version,
               round(100*sum(case when p.a_tiempo then f.toneladas else 0 end)/sum(f.toneladas),2) pct_correcto,
               round(100*sum(case when pr.f <= p.fecha_compromiso then f.toneladas else 0 end)/sum(f.toneladas),2) pct_primera_version
        from silver_logistica.int_viajes__puntualidad p
        join primera pr using(id_viaje) join gold_logistica.fct_embarques f using(id_viaje)"""),

    ("H11", "FechaCompromiso es 00:00 y FechaEntrega trae hora",
     "Comparar timestamps marca tarde cualquier entrega del día del compromiso.",
     """select count(*) viajes_con_pod,
               sum(p.a_tiempo::int) a_tiempo_comparando_fechas,
               sum((e.fecha_entrega <= v.fecha_compromiso)::int) a_tiempo_comparando_timestamps,
               round(100*sum(case when p.a_tiempo then f.toneladas else 0 end)/sum(f.toneladas),2) pct_ton_correcto,
               round(100*sum(case when e.fecha_entrega <= v.fecha_compromiso then f.toneladas else 0 end)/sum(f.toneladas),2) pct_ton_ingenuo
        from silver_logistica.int_viajes__puntualidad p
        join staging.stg_fle__entregas e using(id_viaje) join staging.stg_fle__viajes v using(id_viaje)
        join gold_logistica.fct_embarques f using(id_viaje)"""),

    ("H12", "El segmento de 13 clientes cambia durante el año",
     "Usar el segmento actual reasigna toneladas embarcadas antes del cambio.",
     """with actual as (select cla_cliente, segmento seg_actual from silver_logistica.int_clientes__vigencia
                         where vigente_hasta is null)
        select f.segmento_cliente segmento_correcto, a.seg_actual segmento_ingenuo,
               count(*) partidas, round(sum(f.toneladas),3) toneladas
        from gold_logistica.fct_partidas_embarque f join actual a using(cla_cliente)
        where f.segmento_cliente <> a.seg_actual group by 1,2 order by 4 desc"""),

    ("H13", "Clientes 9001, 9002 y 9003 no existen en el maestro",
     "Un join interno los descarta: se pierden toneladas y cambia el % a tiempo.",
     """select (select round(sum(toneladas),3) from gold_logistica.fct_partidas_embarque
                 where segmento_cliente = 'NO_IDENTIFICADO') toneladas_no_identificado_embarcadas,
               (select round(100*sum(case when segmento_cliente = 'NO_IDENTIFICADO' then toneladas else 0 end)/sum(toneladas),2)
                 from gold_logistica.fct_partidas_embarque) pct_de_toneladas_embarcadas,
               round(sum(case when segmento_cliente = 'NO_IDENTIFICADO' then toneladas else 0 end),3) toneladas_no_identificado_con_pod,
               round(100*sum(case when a_tiempo then toneladas else 0 end)/sum(toneladas),2) pct_a_tiempo_global_con,
               round(100*sum(case when a_tiempo and segmento_cliente <> 'NO_IDENTIFICADO' then toneladas else 0 end)
                     / sum(case when segmento_cliente <> 'NO_IDENTIFICADO' then toneladas end),2) pct_a_tiempo_global_si_se_descartan
        from gold_logistica.fct_partidas_embarque where tiene_pod"""),

    ("H14", "Segmento con espacios y mayúsculas mezcladas ('Constructora ')",
     "Sin normalizar, aparecen categorías falsas y cambios de segmento inexistentes.",
     """with v as (select distinct cast(ClaCliente as integer) cla_cliente, Segmento seg,
                        substr(_ab_cdc_updated_at,1,10) d, cast(_ab_cdc_lsn as bigint) lsn
                 from landing_vta.vta_cliente where _ab_cdc_deleted_at is null),
             t as (select *, lead(d) over (partition by cla_cliente order by lsn) hasta from v)
        select (select count(*) from v where seg not in ('DISTRIBUIDOR','CONSTRUCTORA','INDUSTRIAL')) versiones_con_texto_sucio,
               count(*) partidas_afectadas, round(sum(f.toneladas),3) toneladas_con_categoria_falsa
        from gold_logistica.fct_partidas_embarque f
        join t on t.cla_cliente = f.cla_cliente and f.fecha_embarque >= cast(t.d as date)
              and (t.hasta is null or f.fecha_embarque < cast(t.hasta as date))
        where t.seg not in ('DISTRIBUIDOR','CONSTRUCTORA','INDUSTRIAL')"""),

    ("H15", "El costo del flete se revisa entre versiones",
     "Usar una versión vieja del costo cambia el flete por tonelada.",
     """with c as (select cast(IdViaje as integer) id_viaje, cast(CostoFlete as decimal(18,2)) cf, cast(_ab_cdc_lsn as bigint) lsn
                 from (select distinct IdViaje, CostoFlete, _ab_cdc_lsn from landing_fle.fle_viaje) where CostoFlete is not null),
             pri as (select id_viaje, cf from (select *, row_number() over (partition by id_viaje order by lsn asc) rn from c) where rn = 1),
             ult as (select id_viaje, cf from (select *, row_number() over (partition by id_viaje order by lsn desc) rn from c) where rn = 1)
        select count(*) filter (where u.cf <> p.cf) viajes_con_costo_revisado,
               round(sum(u.cf),2) costo_correcto, round(sum(p.cf),2) costo_con_primera_version,
               round(sum(u.cf) - sum(p.cf),2) diferencia_mxn
        from gold_logistica.fct_embarques f join pri p using(id_viaje) join ult u using(id_viaje)"""),

    ("H16", "El peso documentado de las partidas se revisa entre versiones",
     "Usar una versión vieja cambia las toneladas.",
     """with p as (select cast(IdViaje as integer) id_viaje, cast(IdPartida as integer) id_partida,
                        cast(PesoKg as decimal(18,3)) kg, cast(_ab_cdc_lsn as bigint) lsn
                 from (select distinct IdViaje, IdPartida, PesoKg, _ab_cdc_lsn from landing_fle.fle_viaje_det)),
             pri as (select id_viaje, id_partida, kg from (select *, row_number() over (partition by id_viaje, id_partida order by lsn asc) rn from p) where rn = 1)
        select count(*) filter (where f.peso_kg <> pri.kg) partidas_con_peso_revisado,
               round(sum(f.peso_kg)/1000,3) toneladas_correcto, round(sum(pri.kg)/1000,3) toneladas_con_primera_version,
               round((sum(f.peso_kg) - sum(pri.kg))/1000,3) diferencia_ton
        from gold_logistica.fct_partidas_embarque f join pri using(id_viaje, id_partida)"""),

    ("H17", "Partidas con mismo viaje, cliente, artículo y peso (posibles duplicados, NO eliminadas)",
     "Observación abierta: si fueran duplicados, las toneladas estarían sobreestimadas.",
     """with g as (select id_viaje, cla_cliente, cla_articulo, peso_kg, count(*) n
                    from staging.stg_fle__viajes_det d
                    where id_viaje in (select id_viaje from silver_logistica.int_viajes__embarcados)
                    group by 1,2,3,4 having count(*) > 1)
        select count(*) grupos, sum(n) partidas_involucradas,
               round(sum(peso_kg*(n-1))/1000,3) toneladas_en_juego,
               round(100*sum(peso_kg*(n-1))/1000/(select sum(toneladas) from gold_logistica.fct_embarques),2) pct_de_toneladas_totales
        from g"""),

    ("H18", "Viajes entregados (ENT) sin POD, y un viaje TRA que sí tiene POD",
     "Sin POD no se puede evaluar la puntualidad: esas toneladas quedan fuera de cumplimiento.",
     """select estatus, tiene_pod, count(*) viajes, round(sum(toneladas),3) toneladas
        from gold_logistica.fct_embarques group by 1,2 order by 1,2"""),

    ("H19", "Cambios de segmento y zona horaria (registro en UTC, embarque en hora local)",
     "¿Algún cambio de segmento cae distinto día en UTC que en Monterrey? (si es 0, no hay impacto en esta carga)",
     """with n as (select cast(ClaCliente as integer) cla_cliente, upper(trim(Segmento)) s,
                        cast(replace(replace(_ab_cdc_updated_at,'T',' '),'Z','') as timestamp) u
                 from (select distinct ClaCliente, Segmento, _ab_cdc_updated_at from landing_vta.vta_cliente where _ab_cdc_deleted_at is null)),
             g as (select *, lag(s) over (partition by cla_cliente order by u) ps from n)
        select count(*) cambios_reales,
               sum((cast(u as date) <> cast(timezone('America/Monterrey', timezone('UTC', u)) as date))::int) cambian_de_dia_en_hora_local
        from g where ps is not null and ps <> s"""),
]


def _plano(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def tabla_md(columnas, filas):
    out = ["| " + " | ".join(columnas) + " |", "|" + "---|" * len(columnas)]
    for f in filas:
        out.append("| " + " | ".join("" if v is None else str(v) for v in f) + " |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(RAIZ / "deacero.duckdb"))
    ap.add_argument("--json", default=str(RAIZ / "reporte" / "impacto_hallazgos.json"))
    ap.add_argument("--sin-json", action="store_true")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print("No existe %s. Corre antes `dbt build`." % args.db)
        return 2
    con = duckdb.connect(args.db, read_only=True)
    for sql in PREPARACION:
        con.execute(sql)

    salida = {}
    for hid, titulo, nota, sql in HALLAZGOS:
        cur = con.execute(sql)
        cols = [c[0] for c in cur.description]
        filas = cur.fetchall()
        salida[hid] = {"titulo": titulo, "nota": nota, "columnas": cols,
                       "filas": [[_plano(v) for v in f] for f in filas]}
        print("### %s. %s\n_%s_\n" % (hid, titulo, nota))
        print(tabla_md(cols, [[_plano(v) for v in f] for f in filas]) + "\n")

    if not args.sin_json:
        ruta = Path(args.json)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=2) + "\n")
        print("JSON escrito en %s" % ruta, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
