{#-
  Puntualidad de entrega por viaje. Grano: un viaje embarcado QUE YA TIENE POD.

  Regla 5: a tiempo si la fecha de entrega del POD es MENOR O IGUAL a la fecha compromiso.
  Solo se evalúan viajes con POD (inner join). Cada partida hereda la puntualidad de su viaje.

  Se comparan FECHAS, no timestamps: FechaCompromiso siempre es 00:00:00 y la entrega trae
  hora, así que comparar timestamps marcaría "tarde" cualquier entrega del mismo día
  (en estos datos: 875 vs 1,171 viajes a tiempo de 1,628 con POD).
-#}
select
    v.id_viaje,
    cast(v.fecha_compromiso as date)  as fecha_compromiso,
    cast(e.fecha_entrega as date)     as fecha_entrega,
    (cast(e.fecha_entrega as date) <= cast(v.fecha_compromiso as date)) as a_tiempo
from {{ ref('int_viajes__embarcados') }} as v
inner join {{ ref('stg_fle__entregas') }} as e
    on v.id_viaje = e.id_viaje
