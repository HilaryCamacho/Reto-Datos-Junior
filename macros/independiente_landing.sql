{#-
  Cálculos INDEPENDIENTES, solo para pruebas.

  Las pruebas de conciliación comparan los marts contra estos cálculos. Se escribieron
  deliberadamente distinto a los modelos para no repetir el mismo error en ambos lados:
    - parten de landing (no de staging)
    - eligen la última versión con max(LSN) + join + distinct (los modelos usan row_number)
    - comparan fechas como TEXTO ISO ('2026-01-31'), no como fechas tipadas
  Si el modelo y este cálculo coinciden, es porque dos caminos distintos llegan al mismo número.
-#}

{# Viajes TRA/ENT vigentes (no borrados), con mes de embarque y costo #}
{% macro indep_viajes_embarcados() %}
    with ultima as (
        select IdViaje, max(cast(_ab_cdc_lsn as bigint)) as lsn
        from {{ source('landing_fle', 'fle_viaje') }}
        group by IdViaje
    ),
    unicas as (
        select distinct l.IdViaje, l.ClaPlanta, l.FechaCompromiso, l.FechaRealEmbarque,
               l.FechaEmbarqueFinal, l.Estatus, l.CostoFlete, l._ab_cdc_deleted_at
        from {{ source('landing_fle', 'fle_viaje') }} as l
        inner join ultima as u
            on l.IdViaje = u.IdViaje and cast(l._ab_cdc_lsn as bigint) = u.lsn
    )
    select
        cast(IdViaje as integer) as id_viaje,
        cast(ClaPlanta as integer) as cla_planta,
        substr(
            case when FechaRealEmbarque is null or FechaRealEmbarque like '1900%'
                 then FechaEmbarqueFinal else FechaRealEmbarque end, 1, 7) as anio_mes,
        substr(FechaCompromiso, 1, 10) as compromiso_txt,
        cast(CostoFlete as decimal(18, 2)) as costo
    from unicas
    where _ab_cdc_deleted_at is null
      and upper(trim(Estatus)) in ('TRA', 'ENT')
{% endmacro %}

{# Partidas vigentes (no borradas) con su peso en kg #}
{% macro indep_partidas() %}
    with ultima as (
        select IdViaje, IdPartida, max(cast(_ab_cdc_lsn as bigint)) as lsn
        from {{ source('landing_fle', 'fle_viaje_det') }}
        group by IdViaje, IdPartida
    ),
    unicas as (
        select distinct d.IdViaje, d.IdPartida, d.ClaCliente, d.PesoKg, d._ab_cdc_deleted_at
        from {{ source('landing_fle', 'fle_viaje_det') }} as d
        inner join ultima as u
            on d.IdViaje = u.IdViaje and d.IdPartida = u.IdPartida
           and cast(d._ab_cdc_lsn as bigint) = u.lsn
    )
    select
        cast(IdViaje as integer) as id_viaje,
        cast(IdPartida as integer) as id_partida,
        cast(ClaCliente as integer) as cla_cliente,
        cast(PesoKg as decimal(18, 3)) as kg
    from unicas
    where _ab_cdc_deleted_at is null
{% endmacro %}

{# POD vigente (no borrado): fecha de entrega como texto ISO #}
{% macro indep_pod() %}
    with ultima as (
        select IdViaje, max(cast(_ab_cdc_lsn as bigint)) as lsn
        from {{ source('landing_fle', 'fle_entrega') }}
        group by IdViaje
    ),
    unicas as (
        select distinct e.IdViaje, e.FechaEntrega, e._ab_cdc_deleted_at
        from {{ source('landing_fle', 'fle_entrega') }} as e
        inner join ultima as u
            on e.IdViaje = u.IdViaje and cast(e._ab_cdc_lsn as bigint) = u.lsn
    )
    select
        cast(IdViaje as integer) as id_viaje,
        substr(FechaEntrega, 1, 10) as entrega_txt
    from unicas
    where _ab_cdc_deleted_at is null
{% endmacro %}
