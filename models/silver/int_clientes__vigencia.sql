{#-
  Historial del segmento de cada cliente como tramos de vigencia (tipo SCD2).
  Grano: un tramo de segmento constante por cliente (cla_cliente, nro_tramo).

  Regla 6 del requerimiento: "el cambio aplica desde el día en que se registra".
    vigente_desde = fecha LOCAL (America/Monterrey) del registro del cambio, inclusive.
    vigente_hasta = fecha local del siguiente registro (exclusive). NULL = vigente hoy.
  Intervalo semiabierto [desde, hasta): un día pertenece a un solo tramo.

  Pasos:
  1. Cada versión trae su fecha de registro; el "siguiente registro" se calcula con
     TODAS las versiones (incluidas las bajas) para que una baja cierre el tramo.
  2. Se descartan las versiones de baja.
  3. Versiones consecutivas con el mismo segmento (re-extracciones, "Constructora " vs
     "CONSTRUCTORA") se colapsan en un solo tramo: solo cuenta un cambio real.
-#}
with versiones as (

    select
        cla_cliente,
        nom_cliente,
        segmento,
        cla_estado,
        es_eliminacion,
        cdc_lsn,
        {{ a_fecha_local('cdc_actualizado_en') }} as fecha_registro
    from {{ ref('stg_vta__clientes') }}

),

con_vecinas as (

    select
        *,
        lead(fecha_registro) over (partition by cla_cliente order by cdc_lsn) as siguiente_registro,
        lag(segmento)        over (partition by cla_cliente order by cdc_lsn) as segmento_previo,
        lag(es_eliminacion)  over (partition by cla_cliente order by cdc_lsn) as previo_eliminado
    from versiones

),

vivas as (

    select
        *,
        case
            when segmento_previo is null then 1
            when previo_eliminado then 1
            when segmento_previo <> segmento then 1
            else 0
        end as inicia_tramo
    from con_vecinas
    where not es_eliminacion

),

numeradas as (

    select
        *,
        sum(inicia_tramo) over (
            partition by cla_cliente
            order by cdc_lsn
            rows between unbounded preceding and current row
        ) as nro_tramo
    from vivas

),

tramos as (

    select
        cla_cliente,
        nro_tramo,
        nom_cliente,
        segmento,
        cla_estado,
        min(fecha_registro) over (partition by cla_cliente, nro_tramo) as vigente_desde,
        siguiente_registro                                             as vigente_hasta,
        row_number() over (
            partition by cla_cliente, nro_tramo
            order by cdc_lsn desc
        ) as orden_en_tramo
    from numeradas

)

select
    cla_cliente,
    cast(nro_tramo as integer)   as nro_tramo,
    nom_cliente,
    segmento,
    cla_estado,
    vigente_desde,
    vigente_hasta,
    (nro_tramo = 1)              as es_primer_tramo
from tramos
where orden_en_tramo = 1
