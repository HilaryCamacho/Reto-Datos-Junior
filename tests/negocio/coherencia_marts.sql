{#-
  Coherencia interna de los dos marts (definiciones del contrato).
  Devuelve filas que violan alguna definición:
    - pct_a_tiempo entre 0 y 100 y igual a 100 * a_tiempo / entregadas
    - toneladas_a_tiempo <= toneladas_entregadas
    - costo_flete_por_ton = costo_flete_mxn / toneladas_embarcadas
    - toneladas y viajes positivos
-#}
select 'cumplimiento_entrega' as mart, anio_mes, segmento_cliente as llave, 'pct fuera de rango o mal calculado' as problema
from {{ ref('cumplimiento_entrega') }}
where pct_a_tiempo < 0
   or pct_a_tiempo > 100
   or toneladas_a_tiempo > toneladas_entregadas
   or abs(pct_a_tiempo - 100.0 * toneladas_a_tiempo / nullif(toneladas_entregadas, 0)) > 0.006

union all

select 'embarques_mensual', anio_mes, cast(cla_planta as varchar), 'costo por tonelada mal calculado o valores no positivos'
from {{ ref('embarques_mensual') }}
where num_viajes <= 0
   or toneladas_embarcadas <= 0
   or abs(costo_flete_por_ton - costo_flete_mxn / toneladas_embarcadas) > 0.006
