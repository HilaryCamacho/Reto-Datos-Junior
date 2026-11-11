{#-
  Dimensión de clientes con historial de segmento (tipo 2).
  Grano: un tramo de segmento constante por cliente (cla_cliente, nro_tramo).
  La lógica de vigencia vive en silver (int_clientes__vigencia); aquí se certifica.
  Para ver el segmento a una fecha: vigente_desde <= fecha AND (vigente_hasta IS NULL OR fecha < vigente_hasta).
-#}
select
    cla_cliente,
    nro_tramo,
    nom_cliente,
    segmento,
    cla_estado,
    vigente_desde,
    vigente_hasta,
    (vigente_hasta is null) as es_vigente
from {{ ref('int_clientes__vigencia') }}
