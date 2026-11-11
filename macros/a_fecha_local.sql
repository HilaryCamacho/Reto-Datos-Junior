{#-
  Convierte un timestamp UTC (sin zona, como los _ab_cdc_* de Airbyte) a la FECHA local
  de planta (America/Monterrey). Se usa para saber "desde qué día" aplica un cambio
  de segmento, ya que el embarque está en hora local y el CDC en UTC.

  Se usa el nombre de la zona (y no "- 6 horas") para no depender de horarios de verano.
  timezone('UTC', x)  -> interpreta el timestamp ingenuo como UTC (timestamptz)
  timezone('America/Monterrey', ...) -> lo expresa en hora local, sin depender de la
  zona del equipo donde se ejecute dbt.
-#}
{% macro a_fecha_local(columna_utc) -%}
    cast(timezone('America/Monterrey', timezone('UTC', {{ columna_utc }})) as date)
{%- endmacro %}
