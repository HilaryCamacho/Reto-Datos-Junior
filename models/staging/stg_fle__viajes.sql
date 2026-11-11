{#-
  Staging 1:1 de fle_viaje: tipado, nombres en español, limpieza y deduplicación.
  SIN lógica de negocio (no filtra por estatus ni elige la fecha de embarque).

  Decisiones:
  - Cada fila de landing es una VERSIÓN del viaje: nos quedamos con la última por LSN.
  - Airbyte repite filas idénticas (mismo LSN); empatan y da igual cuál se elija.
  - Si la última versión es un borrado (_ab_cdc_deleted_at), el viaje ya no existe.
  - 1900-01-01 es una fecha centinela del origen para "no capturada": se vuelve NULL.
  - Estatus llega con mayúsculas/minúsculas y espacios mezclados: upper(trim()).
  - cast (y no try_cast): si el origen cambia de formato, queremos que falle y se note.
-#}
with fuente as (

    select * from {{ source('landing_fle', 'fle_viaje') }}

),

tipado as (

    select
        cast(IdViaje as integer)                                                    as id_viaje,
        cast(ClaPlanta as integer)                                                  as cla_planta,
        cast(FechaCompromiso as timestamp)                                          as fecha_compromiso,
        nullif(cast(FechaRealEmbarque as timestamp), cast('1900-01-01' as timestamp))   as fecha_real_embarque,
        nullif(cast(FechaEmbarqueFinal as timestamp), cast('1900-01-01' as timestamp))  as fecha_embarque_final,
        upper(trim(Estatus))                                                        as estatus,
        cast(CostoFlete as decimal(18, 2))                                          as costo_flete_mxn,
        cast(_ab_cdc_lsn as bigint)                                                 as cdc_lsn,
        cast(_ab_cdc_updated_at as timestamp)                                       as cdc_actualizado_en,
        cast(_ab_cdc_deleted_at as timestamp)                                       as cdc_eliminado_en,
        cast(_airbyte_extracted_at as timestamp)                                    as extraido_en
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
    cla_planta,
    fecha_compromiso,
    fecha_real_embarque,
    fecha_embarque_final,
    estatus,
    costo_flete_mxn,
    cdc_lsn,
    cdc_actualizado_en,
    extraido_en
from versionado
where orden_version = 1
  and cdc_eliminado_en is null
