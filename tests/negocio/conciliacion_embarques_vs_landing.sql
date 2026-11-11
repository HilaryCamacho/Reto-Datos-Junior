{#-
  REGLAS 1, 2, 3 y 4 (fecha, estatus, toneladas, flete): reconciliación del mart contra un
  cálculo independiente desde landing (ver macros/independiente_landing.sql).

  Falla (devuelve filas) si, para algún mes x planta, difieren viajes, toneladas o costo.
  Cubre varios errores a la vez: fan-out del flete por partidas, incluir PRO/CAN o viajes
  borrados, usar la fecha equivocada, elegir una versión vieja, dividir mal entre 1,000.

  Los costos y las toneladas se agregan en subconsultas SEPARADAS: así este cálculo no puede
  caer en el error de multiplicar el flete por partidas que justamente se quiere detectar.
-#}
with viajes as (

    {{ indep_viajes_embarcados() }}

),

partidas as (

    {{ indep_partidas() }}

),

costo_y_viajes as (

    select anio_mes, cla_planta, count(*) as viajes, sum(costo) as costo
    from viajes
    group by anio_mes, cla_planta

),

toneladas as (

    select v.anio_mes, v.cla_planta, sum(p.kg) / 1000 as toneladas
    from viajes as v
    inner join partidas as p on v.id_viaje = p.id_viaje
    group by v.anio_mes, v.cla_planta

),

esperado as (

    select c.anio_mes, c.cla_planta, c.viajes, t.toneladas, c.costo
    from costo_y_viajes as c
    left join toneladas as t
        on c.anio_mes = t.anio_mes and c.cla_planta = t.cla_planta

)

select
    coalesce(m.anio_mes, e.anio_mes)       as anio_mes,
    coalesce(m.cla_planta, e.cla_planta)   as cla_planta,
    m.num_viajes                           as viajes_mart,
    e.viajes                               as viajes_esperado,
    m.toneladas_embarcadas                 as toneladas_mart,
    e.toneladas                            as toneladas_esperado,
    m.costo_flete_mxn                      as costo_mart,
    e.costo                                as costo_esperado
from {{ ref('embarques_mensual') }} as m
full outer join esperado as e
    on m.anio_mes = e.anio_mes and m.cla_planta = e.cla_planta
where m.anio_mes is null
   or e.anio_mes is null
   or m.num_viajes <> e.viajes
   or abs(m.toneladas_embarcadas - e.toneladas) > 0.0005
   or abs(m.costo_flete_mxn - e.costo) > 0.005
