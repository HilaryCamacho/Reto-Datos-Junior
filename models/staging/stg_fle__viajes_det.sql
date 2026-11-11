{#-
  Staging 1:1 de fle_viaje_det (partidas del viaje).
  Llave: (id_viaje, id_partida). Misma lógica de versiones que stg_fle__viajes.

  Ojo: el peso de las partidas de un viaje es un reparto del peso total del viaje
  (verificado en el perfilado: la suma por viaje nunca excede 36,270 kg), así que
  sumar partidas es correcto. Esta capa NO descarta partidas de viajes borrados;
  eso se resuelve al unir con stg_fle__viajes (ver HALLAZGOS.md).
-#}
with fuente as (

    select * from {{ source('landing_fle', 'fle_viaje_det') }}

),

tipado as (

    select
        cast(IdViaje as integer)                as id_viaje,
        cast(IdPartida as integer)              as id_partida,
        cast(ClaCliente as integer)             as cla_cliente,
        cast(ClaArticulo as integer)            as cla_articulo,
        cast(PesoKg as decimal(18, 3))          as peso_kg,
        cast(_ab_cdc_lsn as bigint)             as cdc_lsn,
        cast(_ab_cdc_updated_at as timestamp)   as cdc_actualizado_en,
        cast(_ab_cdc_deleted_at as timestamp)   as cdc_eliminado_en,
        cast(_airbyte_extracted_at as timestamp) as extraido_en
    from fuente

),

versionado as (

    select
        *,
        row_number() over (
            partition by id_viaje, id_partida
            order by cdc_lsn desc, cdc_actualizado_en desc, extraido_en desc
        ) as orden_version
    from tipado

)

select
    id_viaje,
    id_partida,
    cla_cliente,
    cla_articulo,
    peso_kg,
    cdc_lsn,
    cdc_actualizado_en,
    extraido_en
from versionado
where orden_version = 1
  and cdc_eliminado_en is null
