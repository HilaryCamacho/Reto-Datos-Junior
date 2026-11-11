{#-
  Carga los CSV replicados a la capa landing de DuckDB, tal cual llegan:
  todas las columnas como texto (all_varchar) y sin ninguna limpieza.

  - Lee TODAS las carpetas carga_* (glob), por lo que una carga nueva se
    agrega sola. Las filas repetidas se resuelven en staging con el LSN.
  - `_archivo_origen` guarda de qué archivo vino cada fila (trazabilidad).
  - create or replace => idempotente: correr N veces deja el mismo resultado.
-#}
{% macro cargar_landing() %}
    {% set tablas = [
        ('landing_fle', 'fle_viaje'),
        ('landing_fle', 'fle_viaje_det'),
        ('landing_fle', 'fle_entrega'),
        ('landing_vta', 'vta_cliente'),
        ('landing_opc', 'opc_planta')
    ] %}

    {# `execute` es falso mientras dbt lee el proyecto; solo cargamos al ejecutar #}
    {% if execute %}
        {% for esquema, tabla in tablas %}
            {% do run_query('create schema if not exists ' ~ esquema) %}
            {% set sql %}
                create or replace table {{ esquema }}.{{ tabla }} as
                select *
                from read_csv(
                    '{{ var("ruta_replica") }}/carga_*/{{ tabla }}.csv',
                    all_varchar = true,
                    header = true,
                    filename = '_archivo_origen'
                )
            {% endset %}
            {% do run_query(sql) %}
            {{ log('landing cargada: ' ~ esquema ~ '.' ~ tabla, info=True) }}
        {% endfor %}
    {% endif %}
{% endmacro %}
