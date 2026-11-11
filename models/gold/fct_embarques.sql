{#-
  Hecho de embarques. Grano: un viaje embarcado (TRA/ENT).

  Regla 3: toneladas = peso DOCUMENTADO de las partidas / 1,000.
  Las partidas se agregan a nivel viaje ANTES de unirse: así el costo de flete
  (que es por viaje) nunca se multiplica por el número de partidas.
-#}
with partidas_por_viaje as (

    select
        id_viaje,
        count(*)       as num_partidas,
        sum(peso_kg)   as peso_kg_total
    from {{ ref('stg_fle__viajes_det') }}
    group by id_viaje

)

select
    v.id_viaje,
    v.cla_planta,
    v.estatus,
    v.fecha_embarque,
    cast(extract(year from v.fecha_embarque) as {{ dbt.type_string() }})
        || '-' ||
    lpad(cast(extract(month from v.fecha_embarque) as {{ dbt.type_string() }}), 2, '0')
                                                                as anio_mes,
    v.origen_fecha_embarque,
    v.costo_flete_mxn,
    coalesce(p.num_partidas, 0)                                 as num_partidas,
    coalesce(p.peso_kg_total, 0)                                as peso_kg_total,
    cast(coalesce(p.peso_kg_total, 0) / 1000 as decimal(18, 3)) as toneladas,
    (pun.id_viaje is not null)                                  as tiene_pod,
    pun.fecha_entrega,
    pun.a_tiempo
from {{ ref('int_viajes__embarcados') }} as v
left join partidas_por_viaje as p
    on v.id_viaje = p.id_viaje
left join {{ ref('int_viajes__puntualidad') }} as pun
    on v.id_viaje = pun.id_viaje
