{#-
  REGLA 6: el segmento es el que tenía el cliente el DÍA DEL EMBARQUE, no el actual.
  Verificado a mano contra vta_cliente.csv:

    Cliente 1002: DISTRIBUIDOR hasta 2026-02-21; CONSTRUCTORA desde 2026-02-22.
    Cliente 1055: INDUSTRIAL hasta 2026-02-04; CONSTRUCTORA desde 2026-02-05
                  (sus versiones intermedias "Constructora " y "CONSTRUCTORA" no son un cambio).
    Cliente 1009: INDUSTRIAL hasta 2026-04-03; DISTRIBUIDOR desde 2026-04-04.

  Si el modelo usara el segmento ACTUAL, todos los embarques anteriores al cambio saldrían
  con el segmento nuevo y esta prueba fallaría. Las partidas de estos clientes se evalúan
  una por una, antes y después de la fecha de cambio.
-#}
with reglas as (

    select 1002 as cla_cliente, date '2026-02-22' as cambio, 'DISTRIBUIDOR' as antes, 'CONSTRUCTORA' as despues union all
    select 1055,               date '2026-02-05',            'INDUSTRIAL',            'CONSTRUCTORA'              union all
    select 1009,               date '2026-04-04',            'INDUSTRIAL',            'DISTRIBUIDOR'

)

select
    f.cla_cliente,
    f.id_viaje,
    f.id_partida,
    f.fecha_embarque,
    f.segmento_cliente,
    case when f.fecha_embarque < r.cambio then r.antes else r.despues end as segmento_esperado
from {{ ref('fct_partidas_embarque') }} as f
inner join reglas as r on f.cla_cliente = r.cla_cliente
where f.segmento_cliente <>
      case when f.fecha_embarque < r.cambio then r.antes else r.despues end
