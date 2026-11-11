{#-
  Mart de Logística: embarques por planta y mes. Contrato: docs/contrato-marts.md
  Grano: una fila por anio_mes x cla_planta (solo combinaciones con embarques).

  Redondeo: toneladas a 3 decimales, dinero a 2. El costo por tonelada se calcula con
  las sumas SIN redondear y se redondea al final (no se hereda error de redondeo).
-#}
select
    f.anio_mes                                               as anio_mes,
    f.cla_planta                                             as cla_planta,
    p.nom_planta                                             as nom_planta,
    cast(count(*) as integer)                                as num_viajes,
    cast(round(sum(f.toneladas), 3) as decimal(18, 3))       as toneladas_embarcadas,
    cast(round(sum(f.costo_flete_mxn), 2) as decimal(18, 2)) as costo_flete_mxn,
    cast(round(sum(f.costo_flete_mxn) / nullif(sum(f.toneladas), 0), 2) as decimal(18, 2))
                                                             as costo_flete_por_ton
from {{ ref('fct_embarques') }} as f
inner join {{ ref('dim_planta') }} as p
    on f.cla_planta = p.cla_planta
group by f.anio_mes, f.cla_planta, p.nom_planta
