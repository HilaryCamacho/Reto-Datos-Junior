{#-
  Staging de vta_cliente. A diferencia de las demás tablas, aquí se CONSERVAN todas
  las versiones: el negocio necesita el segmento que tenía el cliente el día del
  embarque, así que el historial de cambios es un dato, no ruido.

  Solo se eliminan las copias exactas que repite Airbyte (mismo cliente y mismo LSN).
  La vigencia (desde/hasta) se calcula en gold: dim_cliente.

  - Segmento llega con espacios y capitalización mezclada ("Constructora "): upper(trim()).
  - Las versiones de borrado se conservan con es_eliminacion = true; también cierran
    la vigencia del cliente en dim_cliente.
-#}
with fuente as (

    select * from {{ source('landing_vta', 'vta_cliente') }}

),

tipado as (

    select
        cast(ClaCliente as integer)              as cla_cliente,
        trim(NomCliente)                         as nom_cliente,
        upper(trim(Segmento))                    as segmento,
        upper(trim(ClaEstado))                   as cla_estado,
        cast(_ab_cdc_lsn as bigint)              as cdc_lsn,
        cast(_ab_cdc_updated_at as timestamp)    as cdc_actualizado_en,
        cast(_ab_cdc_deleted_at as timestamp)    as cdc_eliminado_en,
        cast(_airbyte_extracted_at as timestamp) as extraido_en
    from fuente

),

sin_copias as (

    select
        *,
        row_number() over (
            partition by cla_cliente, cdc_lsn
            order by extraido_en desc
        ) as orden_copia
    from tipado

)

select
    cla_cliente,
    nom_cliente,
    segmento,
    cla_estado,
    cdc_lsn,
    cdc_actualizado_en,
    cdc_eliminado_en,
    (cdc_eliminado_en is not null) as es_eliminacion,
    extraido_en
from sin_copias
where orden_copia = 1
