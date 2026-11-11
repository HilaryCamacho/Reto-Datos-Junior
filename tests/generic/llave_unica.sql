{#-
  Prueba genérica: la combinación de columnas es única (grano de la tabla).
  Reemplaza a dbt_utils.unique_combination_of_columns para no depender de paquetes externos.
  Devuelve las llaves repetidas; la prueba falla si devuelve filas.
-#}
{% test llave_unica(model, columnas) %}

select
    {{ columnas | join(', ') }},
    count(*) as repeticiones
from {{ model }}
group by {{ columnas | join(', ') }}
having count(*) > 1

{% endtest %}
