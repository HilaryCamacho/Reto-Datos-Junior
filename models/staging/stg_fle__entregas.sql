{#-
  Staging 1:1 de fle_entrega (POD, comprobante de entrega). Llave: id_viaje.

  Tráfico a veces corrige la fecha del POD (80 casos, ±1 día): se usa la ÚLTIMA versión.
  En 11 de esos casos la corrección cambia el resultado de "a tiempo".
-#}
with fuente as (

    select * from {{ source('landing_fle', 'fle_entrega') }}

),

tipado as (

    select
        cast(IdViaje as integer)                as id_viaje,
        cast(FechaEntrega as timestamp)         as fecha_entrega,
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
            partition by id_viaje
            order by cdc_lsn desc, cdc_actualizado_en desc, extraido_en desc
        ) as orden_version
    from tipado

)

select
    id_viaje,
    fecha_entrega,
    cdc_lsn,
    cdc_actualizado_en,
    extraido_en
from versionado
where orden_version = 1
  and cdc_eliminado_en is null
