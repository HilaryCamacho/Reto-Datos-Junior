{#-
  CASOS CONOCIDOS, verificados a mano contra los CSV (ver HALLAZGOS.md). Cada fila de
  `esperado` es un viaje real con la respuesta correcta; la prueba falla si el modelo no la da.

  Regla 1 (fecha de embarque):
    250312 y 250313: fecha real 2026-01-31, fecha final 2026-02-01 -> deben contar en ENERO.
    251800: fecha real 2026-06-30, fecha final 2026-07-01 -> JUNIO (la final cae fuera del rango).
    250284: sin fecha real, final 2026-01-28 -> respaldo FechaEmbarqueFinal, enero.

  Regla 5 (a tiempo, comparando fechas y usando el POD vigente):
    250001, 250005: entrega el MISMO día del compromiso, a las 04:33 y 18:07 -> A TIEMPO
                    (comparando timestamps saldrían tarde).
    250006: entrega un día después del compromiso -> TARDE.
    250180: el POD se corrigió de 01-24 a 01-25 (compromiso 01-24) -> TARDE con la última versión.
    250312, 250397: el POD se corrigió un día antes (02-03 -> 02-02 y 02-09 -> 02-08) -> A TIEMPO
                    con la última versión.
-#}
with esperado as (

    select 250312 as id_viaje, '2026-01' as anio_mes_esperado, cast(true  as boolean) as a_tiempo_esperado union all
    select 250313,             '2026-01',                      cast(null  as boolean)                      union all
    select 251800,             '2026-06',                      cast(null  as boolean)                      union all
    select 250284,             '2026-01',                      cast(null  as boolean)                      union all
    select 250001,             '2026-01',                      true                                        union all
    select 250005,             '2026-01',                      true                                        union all
    select 250006,             '2026-01',                      false                                       union all
    select 250180,             '2026-01',                      false                                       union all
    select 250397,             '2026-02',                      true

)

select
    e.id_viaje,
    f.anio_mes,
    e.anio_mes_esperado,
    f.a_tiempo,
    e.a_tiempo_esperado
from esperado as e
left join {{ ref('fct_embarques') }} as f on e.id_viaje = f.id_viaje
where f.id_viaje is null
   or f.anio_mes <> e.anio_mes_esperado
   or (e.a_tiempo_esperado is not null and f.a_tiempo is distinct from e.a_tiempo_esperado)
