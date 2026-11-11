{#-
  Partidas de viajes embarcados con el segmento del cliente VIGENTE EL DÍA DEL EMBARQUE.
  Grano: una partida (id_viaje, id_partida).

  Regla 6: segmento vigente el día del embarque, no el actual.
  Regla 7: cliente que no existe en el maestro -> NO_IDENTIFICADO (sus toneladas no se pierden).

  Al partir de int_viajes__embarcados (inner join) esta tabla ya excluye por construcción:
  partidas de viajes PRO/CAN y partidas de viajes borrados en el origen.

  origen_segmento documenta cómo se resolvió cada partida (útil para auditar):
    VIGENTE_EN_FECHA            -> tramo de vigencia que cubre la fecha de embarque
    PRIMER_SEGMENTO_CONOCIDO    -> embarque anterior al primer registro del cliente (supuesto)
    CLIENTE_DADO_DE_BAJA        -> el cliente existió pero estaba dado de baja ese día
    CLIENTE_NO_EXISTE_EN_MAESTRO-> nunca estuvo en el maestro (p. ej. 9001, 9002, 9003)
-#}
with partidas as (

    select
        d.id_viaje,
        d.id_partida,
        d.cla_cliente,
        d.peso_kg,
        v.cla_planta,
        v.fecha_embarque
    from {{ ref('stg_fle__viajes_det') }} as d
    inner join {{ ref('int_viajes__embarcados') }} as v
        on d.id_viaje = v.id_viaje

),

resuelto as (

    select
        p.id_viaje,
        p.id_partida,
        p.cla_cliente,
        p.peso_kg,
        p.cla_planta,
        p.fecha_embarque,
        case
            when t.segmento is not null then t.segmento
            when primero.cla_cliente is not null
                 and p.fecha_embarque < primero.vigente_desde then primero.segmento
            else 'NO_IDENTIFICADO'
        end as segmento_cliente,
        case
            when t.segmento is not null then 'VIGENTE_EN_FECHA'
            when primero.cla_cliente is not null
                 and p.fecha_embarque < primero.vigente_desde then 'PRIMER_SEGMENTO_CONOCIDO'
            when primero.cla_cliente is not null then 'CLIENTE_DADO_DE_BAJA'
            else 'CLIENTE_NO_EXISTE_EN_MAESTRO'
        end as origen_segmento
    from partidas as p
    left join {{ ref('int_clientes__vigencia') }} as t
        on  p.cla_cliente = t.cla_cliente
        and p.fecha_embarque >= t.vigente_desde
        and (t.vigente_hasta is null or p.fecha_embarque < t.vigente_hasta)
    left join {{ ref('int_clientes__vigencia') }} as primero
        on  p.cla_cliente = primero.cla_cliente
        and primero.es_primer_tramo

)

select * from resuelto
