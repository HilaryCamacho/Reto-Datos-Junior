{#-
  REGLA 7: las toneladas de clientes que no existen en el maestro NO se pierden; se reportan
  como NO_IDENTIFICADO. Se compara contra un cálculo independiente: partidas de viajes
  embarcados cuyo ClaCliente nunca aparece en vta_cliente.

  Falla si el total difiere, es decir, si se pierden (o se inventan) toneladas huérfanas.
-#}
with viajes as (

    {{ indep_viajes_embarcados() }}

),

partidas as (

    {{ indep_partidas() }}

),

clientes_en_maestro as (

    select distinct cast(ClaCliente as integer) as cla_cliente
    from {{ source('landing_vta', 'vta_cliente') }}

),

esperado as (

    select sum(p.kg) / 1000 as toneladas
    from partidas as p
    inner join viajes as v on p.id_viaje = v.id_viaje
    left join clientes_en_maestro as c on p.cla_cliente = c.cla_cliente
    where c.cla_cliente is null

),

modelo as (

    select sum(toneladas) as toneladas
    from {{ ref('fct_partidas_embarque') }}
    where segmento_cliente = 'NO_IDENTIFICADO'

)

select modelo.toneladas as toneladas_modelo, esperado.toneladas as toneladas_esperado
from modelo
cross join esperado
where abs(coalesce(modelo.toneladas, 0) - coalesce(esperado.toneladas, 0)) > 0.0005
