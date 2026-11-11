{#-
  Por defecto dbt arma el esquema como <schema del target>_<schema personalizado>
  (por ejemplo main_mart_logistica). El contrato exige que el esquema se llame
  exactamente `mart_logistica`, así que usamos el esquema personalizado tal cual.
-#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
