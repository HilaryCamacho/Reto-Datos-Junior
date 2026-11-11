{#-
  Mart de Logística: cumplimiento de entrega por segmento y mes de embarque.
  Contrato: docs/contrato-marts.md
  Grano: una fila por anio_mes x segmento_cliente (solo combinaciones con POD).

  Solo entran partidas cuyo viaje ya tiene POD (tiene_pod). Cada partida hereda la
  puntualidad de su viaje y aporta SUS toneladas al segmento de SU cliente.
-#}
select
    anio_mes                                                        as anio_mes,
    segmento_cliente                                                as segmento_cliente,
    cast(round(sum(toneladas), 3) as decimal(18, 3))                as toneladas_entregadas,
    cast(round(sum(case when a_tiempo then toneladas else 0 end), 3) as decimal(18, 3))
                                                                    as toneladas_a_tiempo,
    cast(round(100 * sum(case when a_tiempo then toneladas else 0 end)
               / nullif(sum(toneladas), 0), 2) as decimal(18, 2))   as pct_a_tiempo
from {{ ref('fct_partidas_embarque') }}
where tiene_pod
group by anio_mes, segmento_cliente
