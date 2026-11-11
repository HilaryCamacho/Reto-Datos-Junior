{#-
  REGLA 5 (a tiempo) y REGLA 7 (toneladas no se pierden): por mes de embarque, el total de
  toneladas entregadas y a tiempo del mart (sumando los segmentos) debe coincidir con un
  cálculo independiente desde landing que no usa segmentos.

  - Si algún cliente huérfano o cambio de segmento hiciera perder toneladas, el total por
    mes no cuadraría.
  - La puntualidad aquí se calcula comparando FECHAS como texto ISO (YYYY-MM-DD); si el
    modelo comparara timestamps, el total a tiempo sería muy distinto.
-#}
with viajes as (

    {{ indep_viajes_embarcados() }}

),

partidas as (

    {{ indep_partidas() }}

),

pod as (

    {{ indep_pod() }}

),

esperado as (

    select
        v.anio_mes,
        sum(p.kg) / 1000 as entregadas,
        sum(case when pod.entrega_txt <= v.compromiso_txt then p.kg else 0 end) / 1000 as a_tiempo
    from viajes as v
    inner join pod on v.id_viaje = pod.id_viaje
    inner join partidas as p on v.id_viaje = p.id_viaje
    group by v.anio_mes

),

mart as (

    select
        anio_mes,
        sum(toneladas_entregadas) as entregadas,
        sum(toneladas_a_tiempo)   as a_tiempo
    from {{ ref('cumplimiento_entrega') }}
    group by anio_mes

)

select
    coalesce(m.anio_mes, e.anio_mes) as anio_mes,
    m.entregadas  as entregadas_mart,  e.entregadas as entregadas_esperado,
    m.a_tiempo    as a_tiempo_mart,    e.a_tiempo   as a_tiempo_esperado
from mart as m
full outer join esperado as e on m.anio_mes = e.anio_mes
where m.anio_mes is null
   or e.anio_mes is null
   or abs(m.entregadas - e.entregadas) > 0.0005
   or abs(m.a_tiempo - e.a_tiempo) > 0.0005
