{#- Staging 1:1 de opc_planta (catálogo de plantas). Llave: cla_planta. -#}
with fuente as (

    select * from {{ source('landing_opc', 'opc_planta') }}

),

tipado as (

    select
        cast(ClaPlanta as integer)               as cla_planta,
        trim(NomPlanta)                          as nom_planta,
        upper(trim(ClaPais))                     as cla_pais,
        cast(_ab_cdc_lsn as bigint)              as cdc_lsn,
        cast(_ab_cdc_updated_at as timestamp)    as cdc_actualizado_en,
        cast(_ab_cdc_deleted_at as timestamp)    as cdc_eliminado_en,
        cast(_airbyte_extracted_at as timestamp) as extraido_en
    from fuente

),

versionado as (

    select
        *,
        row_number() over (
            partition by cla_planta
            order by cdc_lsn desc, cdc_actualizado_en desc, extraido_en desc
        ) as orden_version
    from tipado

)

select
    cla_planta,
    nom_planta,
    cla_pais,
    cdc_lsn,
    cdc_actualizado_en,
    extraido_en
from versionado
where orden_version = 1
  and cdc_eliminado_en is null
