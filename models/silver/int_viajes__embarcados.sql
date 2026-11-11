{#-
  Viajes que SÍ salieron de planta. Grano: un viaje.

  Regla 1: fecha de embarque = FechaRealEmbarque; si no está capturada,
           FechaEmbarqueFinal. Ya viene en hora local de planta, así que el mes
           se toma directo de la fecha, sin conversión de zona horaria.
  Regla 2: solo TRA (en tránsito) y ENT (entregado). PRO no ha salido y CAN nunca salió.
  Regla 4: el costo de flete es POR VIAJE. Por eso aquí NO hay join con partidas;
           el peso se agrega aparte (fct_embarques) para no multiplicar el costo.
-#}
with viajes as (

    select * from {{ ref('stg_fle__viajes') }}
    where estatus in ('TRA', 'ENT')

)

select
    id_viaje,
    cla_planta,
    estatus,
    fecha_compromiso,
    cast(coalesce(fecha_real_embarque, fecha_embarque_final) as date) as fecha_embarque,
    case
        when fecha_real_embarque is not null then 'FechaRealEmbarque'
        else 'FechaEmbarqueFinal'
    end as origen_fecha_embarque,
    costo_flete_mxn
from viajes
