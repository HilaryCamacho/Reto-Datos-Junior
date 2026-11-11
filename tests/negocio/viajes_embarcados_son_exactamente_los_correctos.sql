{#-
  REGLA 2 (qué cuenta como embarcado): el conjunto de viajes de fct_embarques debe ser
  EXACTAMENTE el de un cálculo independiente (TRA/ENT, última versión, no borrados).

  Falla si sobra un viaje (p. ej. un PRO/CAN o un viaje borrado en el origen) o si falta uno.
-#}
with esperado as (

    {{ indep_viajes_embarcados() }}

)

select
    coalesce(f.id_viaje, e.id_viaje) as id_viaje,
    case when f.id_viaje is null then 'FALTA en fct_embarques'
         else 'SOBRA en fct_embarques' end as problema
from {{ ref('fct_embarques') }} as f
full outer join esperado as e on f.id_viaje = e.id_viaje
where f.id_viaje is null or e.id_viaje is null
