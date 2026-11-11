{#-
  Hecho de partidas embarcadas. Grano: una partida (id_viaje, id_partida).
  Trae el segmento vigente el día del embarque y la puntualidad heredada de su viaje.
  Es la base del mart cumplimiento_entrega (que se mide en toneladas por segmento).
-#}
select
    s.id_viaje,
    s.id_partida,
    s.cla_cliente,
    s.segmento_cliente,
    s.origen_segmento,
    s.cla_planta,
    s.fecha_embarque,
    f.anio_mes,
    s.peso_kg,
    cast(s.peso_kg / 1000 as decimal(18, 3)) as toneladas,
    f.tiene_pod,
    f.a_tiempo
from {{ ref('int_partidas__segmento') }} as s
inner join {{ ref('fct_embarques') }} as f
    on s.id_viaje = f.id_viaje
