# Hallazgos de calidad de datos

Problemas encontrados en la réplica `data/replica/carga_1/` (cinco tablas, SQL Server → Airbyte CDC), y qué hice con cada uno.

**Cómo leer este documento.** Cada hallazgo responde las cuatro preguntas del reto: *qué vi*, *cómo lo detecté*, *cómo afecta al resultado* y *qué hice*. Los números de "cómo afecta" **no son estimaciones**: salen de `python tools/analisis_impacto.py`, que calcula para cada problema el resultado correcto (el del proyecto) y el **ingenuo** (el que saldría si el problema se ignorara). Se pueden reproducir con ese comando y están guardados en [`reporte/impacto_hallazgos.json`](reporte/impacto_hallazgos.json).

**Línea base.** 1,689 viajes embarcados · 47,091.622 t · 28,421,589.81 MXN de flete · enero a junio de 2026 · 4 plantas.

## Resumen

| ID | Hallazgo | Si se ignorara | Gravedad |
|---|---|---|---|
| H08 | El flete es por viaje, pero el viaje tiene varias partidas | Flete **+105.8 %** (58.5 M vs 28.4 M MXN) | Alta |
| H11 | `FechaCompromiso` a las 00:00 vs `FechaEntrega` con hora | % a tiempo **53.91 %** en vez de **71.77 %** | Alta |
| H01 | La tabla trae historia de versiones, no el estado actual | 3,629 viajes y 50,285 t en vez de 1,689 y 47,092 t | Alta |
| H04 | Estatus con mayúsculas y espacios mezclados | **Se pierden 194 viajes** (5,416 t, 3.3 M MXN) | Alta |
| H05 | Fecha centinela `1900-01-01` en viajes embarcados | 226 viajes (6,289 t) caen en el mes `1900-01` | Alta |
| H12 | El segmento de 13 clientes cambia en el año | 3,336 t (7.1 %) en el segmento equivocado | Alta |
| H14 | Segmento con espacios y capitalización mezclada | 3,413 t en una categoría que no existe | Media |
| H13 | Clientes 9001, 9002 y 9003 no están en el maestro | Se pierden 983 t (2.09 %) | Media |
| H03 | Viajes borrados en el origen con estatus `TRA`/`ENT` | +19 viajes fantasma (572 t, 332 mil MXN) | Media |
| H09 | Viajes `PRO`/`CAN` traen partidas con peso | +3,338 t que nunca salieron | Media |
| H06 | 591 viajes sin fecha real válida dependen del respaldo | Esos 591 viajes (35 %) quedarían sin mes | Media |
| H07 | Fecha real y fecha final en meses distintos | 3 viajes (82 t) en el mes equivocado | Baja |
| H15 | El costo del flete se revisa entre versiones | 348 mil MXN (1.2 %) de diferencia | Baja |
| H10 | Tráfico corrige la fecha del POD | 11 viajes cambian de clasificación (0.14 pp) | Baja |
| H02 | Filas duplicadas exactas de Airbyte | 103 + 101 + 4 copias | Baja (si se deduplica) |
| H16 | El peso documentado se revisa entre versiones | 3.06 t | Baja |
| H17 | Partidas con el mismo viaje, cliente, artículo y peso | **Abierto**: hasta 796 t (1.7 %) | Pregunta abierta |
| H18 | 25 viajes `ENT` sin POD (más 36 `TRA`) | 704 t no se pueden evaluar | Informativo |
| H19 | Zona horaria del CDC (UTC) vs embarque (local) | Cero cambios de día en esta carga | Sin impacto hoy |

Además, hay **diferencias entre la documentación y los datos** (sección final).

---

## A. Replicación y CDC

### H01 · La tabla trae historia de versiones, no el estado actual

- **Qué vi.** `fle_viaje` tiene 5,584 filas para 1,827 viajes (3 versiones por viaje en promedio). Lo mismo ocurre en `fle_viaje_det` (3,965 filas, 3,757 partidas), `fle_entrega` (1,708 filas, 1,628 viajes) y `vta_cliente` (110 filas, 82 clientes). Un viaje pasa de `PRO` a `TRA` a `ENT`, y cambian su costo, su peso y la fecha del POD.
- **Cómo lo detecté.** Comparé `count(*)` con `count(distinct llave)` en cada tabla y la distribución de versiones por llave. Verifiqué que ordenar por `_ab_cdc_lsn` y por `_ab_cdc_updated_at` da la misma última versión en todos los viajes (0 diferencias), así que el orden es consistente.
- **Cómo afecta.** Sin quedarse con la última versión: **3,629 viajes en lugar de 1,689** y 50,285 t en lugar de 47,092 t. La llave "primaria" del diccionario (`IdViaje (PK)`) no es única en landing.
- **Qué hice.** Cada modelo `stg_` conserva la última versión por LSN (`row_number() ... order by cdc_lsn desc`). Prueba: `unique` sobre la llave en cada staging. **Excepción deliberada:** `stg_vta__clientes` conserva todas las versiones, porque el historial del segmento es un requisito de negocio (H12).

### H02 · Filas duplicadas exactas de Airbyte

- **Qué vi.** 103 filas en `fle_viaje`, 101 en `fle_viaje_det` y 4 en `vta_cliente` son copias exactas de otra: mismo LSN y mismo contenido en todas las columnas. `fle_entrega` no tiene.
- **Cómo lo detecté.** `count(*)` contra `count(*)` de `select distinct`, y búsqueda de LSN repetidos: en los 103 casos del viaje el LSN repetido pertenece al mismo `IdViaje`.
- **Cómo afecta.** No son versiones nuevas. Ordenar solo por LSN deja empates; si dos copias empataran con contenido distinto, el resultado dependería del azar. Aquí son idénticas, así que no cambia el resultado, pero el criterio debe ser determinista.
- **Qué hice.** El orden de deduplicación desempata por `cdc_actualizado_en` y `extraido_en`. En clientes se deduplica por `(cla_cliente, cdc_lsn)`. Prueba: `llave_unica` sobre `(cla_cliente, cdc_lsn)`.

### H03 · Viajes borrados en el origen que conservan estatus `TRA`/`ENT`

- **Qué vi.** 20 filas con `_ab_cdc_deleted_at` en viajes (19 viajes; uno aparece con la fila de borrado duplicada). La fila de borrado **conserva el contenido del último estado**: por ejemplo el viaje 250161 queda como `tra` con costo. También hay 2 clientes borrados (1901 y 1902, sin partidas).
- **Cómo lo detecté.** Filtré `_ab_cdc_deleted_at is not null` y revisé el historial completo de varias llaves. Confirmé que cada fila de borrado es la última versión de su llave. Una prueba `relationships` entre partidas y viajes avisa de **39 partidas huérfanas** (las de los viajes borrados).
- **Cómo afecta.** Si no se excluyen: **+19 viajes, +571.6 t y +331,901 MXN** que ya no existen en el origen.
- **Qué hice.** El staging descarta la llave si su última versión es un borrado. La prueba de huérfanas está como `warn` (no `error`) a propósito: es un hallazgo conocido que se resuelve al unir con viajes vigentes. Una prueba de negocio (`viajes_embarcados_son_exactamente_los_correctos`) verifica que ningún viaje borrado entre al hecho.

---

## B. Texto y valores

### H04 · Estatus con mayúsculas y espacios mezclados

- **Qué vi.** `Estatus` (documentado como `char(3)` con 4 valores) llega en 20 variantes: `ENT`, `Ent`, `ent`, `ENT `, ` ENT`, etc.
- **Cómo lo detecté.** `select '['||Estatus||']', count(*) group by 1` (los corchetes hacen visibles los espacios).
- **Cómo afecta.** Filtrar con `Estatus in ('TRA','ENT')` sin normalizar **pierde 194 viajes embarcados** (11.5 %), con 5,416 t y 3.3 M MXN. Es un error silencioso: nada falla, solo faltan datos.
- **Qué hice.** `upper(trim(Estatus))` en staging. Prueba: `accepted_values` con exactamente `PRO/TRA/ENT/CAN`.

### H14 · Segmento con espacios y capitalización mezclada

- **Qué vi.** 7 versiones de `Segmento` vienen como `'Constructora '`, `'Industrial '` o `'Distribuidor '`, aunque el diccionario dice que solo existen tres valores en mayúsculas.
- **Cómo lo detecté.** Misma técnica de corchetes sobre `Segmento`. Además, al normalizar, 9 versiones resultan ser el mismo segmento que la anterior (re-extracciones, no cambios reales).
- **Cómo afecta.** Sin normalizar aparecen categorías que no existen y **cambios de segmento falsos**: 3,413 t (245 partidas) quedarían bajo una categoría inexistente.
- **Qué hice.** `upper(trim())` en staging y, al construir los tramos de vigencia, las versiones consecutivas con el mismo segmento se colapsan. Prueba: `accepted_values` en staging, silver y los dos marts.

### H05 · Fecha centinela `1900-01-01` en viajes embarcados

- **Qué vi.** `FechaRealEmbarque` trae `1900-01-01` (1,274 filas) para "no capturada", aunque el diccionario dice "Nulo si no se capturó". **226 viajes embarcados** (`TRA`/`ENT`) la conservan en su última versión.
- **Cómo lo detecté.** Perfilado de nulos y mínimos por columna de fecha. Al principio supuse que el centinela solo aparecía en viajes `PRO`; el análisis de impacto lo desmintió.
- **Cómo afecta.** Sin limpiarla, esos 226 viajes (**6,289 t y 3.8 M MXN**) se agrupan en el mes `1900-01` y desaparecen de su mes real. Con la regla "usar `FechaEmbarqueFinal` si no hay fecha real", el centinela impide aplicar el respaldo porque no es nulo.
- **Qué hice.** `nullif(fecha, '1900-01-01')` en staging, antes de cualquier lógica de negocio.

---

## C. Fechas y puntualidad

### H06 · Viajes embarcados sin fecha real válida dependen del respaldo

- **Qué vi.** 591 viajes embarcados (35 %) no tienen fecha real válida: 365 con valor nulo y 226 con el centinela. Todos tienen `FechaEmbarqueFinal`.
- **Cómo lo detecté.** Conteo de `FechaRealEmbarque` nula o `1900-01-01` por estatus, y comprobación de que ninguno carece de ambas fechas.
- **Cómo afecta.** Usar solo la fecha real dejaría **10,126.8 t + 6,289.4 t** sin mes. El respaldo no es un caso marginal: afecta a más de la tercera parte de los viajes.
- **Qué hice.** `coalesce(fecha_real, fecha_final)` y una columna `origen_fecha_embarque` que documenta cuál se usó. Casos de prueba reales: el viaje 250284 (sin fecha real) cuenta en enero por su fecha final.

### H07 · Fecha real y fecha final caen en meses distintos

- **Qué vi.** La fecha real nunca es posterior a la final, pero en 198 viajes cambia el día y en **3 cambia el mes**: 250312 y 250313 salen el 31 de enero (el documento cierra el 1 de febrero) y 251800 sale el 30 de junio (cierra el 1 de julio).
- **Cómo lo detecté.** Comparé `substr(fecha,1,7)` de ambas columnas.
- **Cómo afecta.** Elegir la fecha final mueve 2 viajes (46.8 t) de enero a febrero y 1 viaje (34.8 t) de junio a julio, un mes que ni siquiera tiene datos.
- **Qué hice.** Regla del requerimiento: la fecha real manda. Prueba con los tres viajes reales (`casos_conocidos_fecha_y_puntualidad`) y una unitaria con datos inventados.

### H11 · `FechaCompromiso` a las 00:00 vs `FechaEntrega` con hora

- **Qué vi.** `FechaCompromiso` es siempre medianoche (1,808 de 1,808) y `FechaEntrega` trae hora.
- **Cómo lo detecté.** Comprobé `FechaCompromiso not like '% 00:00:00.000'` (0 casos) y comparé las dos formas de calcular "a tiempo".
- **Cómo afecta.** **El mayor efecto del proyecto en cumplimiento.** Comparando timestamps, una entrega el mismo día del compromiso (por ejemplo a las 18:07) cuenta como tarde. Resultado: 875 viajes a tiempo (**53.91 %** de las toneladas) contra 1,171 comparando fechas (**71.77 %**). Un error de 18 puntos que no produce ningún aviso.
- **Qué hice.** Comparar `cast(fecha_entrega as date) <= cast(fecha_compromiso as date)`, conforme a la regla 5 ("fecha de entrega menor o igual a la fecha compromiso"). Es una **interpretación** documentada como supuesto en el README. Pruebas: unitaria y casos reales (250001 y 250005 entregan el mismo día y deben ser a tiempo; 250006 entrega un día después y debe ser tarde).

### H10 · Tráfico corrige la fecha del POD

- **Qué vi.** 80 PODs tienen dos versiones, con la fecha de entrega movida un día.
- **Cómo lo detecté.** Llaves con 2 versiones en `fle_entrega` y comparación de las dos fechas contra el compromiso.
- **Cómo afecta.** **11 viajes cambian de clasificación** (por ejemplo el 250180 pasa a tarde y el 250397 a tiempo). En el total apenas se nota (71.77 % vs 71.91 %), pero por mes y segmento puede ser mayor.
- **Qué hice.** Última versión del POD. Pruebas con los viajes 250180, 250312 y 250397.

---

## D. Modelado y reglas de negocio

### H08 · El flete es por viaje, pero el viaje tiene varias partidas

- **Qué vi.** `CostoFlete` vive en el viaje y el peso en las partidas (1 a 4 por viaje; 1,173 viajes tienen 2 o más).
- **Cómo lo detecté.** Es consecuencia directa del grano de las tablas: unir viaje con partidas repite el costo por cada partida.
- **Cómo afecta.** Sumar el costo después del join da **58.5 M MXN contra 28.4 M MXN correctos (+105.8 %)**, y el flete por tonelada se duplica de forma similar. Cambia entre plantas (de +99.8 % en Saltillo a +114.8 % en Houston), así que ni siquiera falla de forma uniforme.
- **Qué hice.** `fct_embarques` tiene grano de viaje: las partidas se agregan por viaje **antes** de unirse y el costo nunca pasa por un join con partidas. Pruebas: conciliación independiente del mart contra landing (agrega costo y toneladas en subconsultas separadas) y `unique` sobre `id_viaje`.

### H09 · Viajes `PRO`/`CAN` traen partidas con peso

- **Qué vi.** 25 viajes `PRO` y 94 `CAN` tienen partidas con peso documentado.
- **Cómo lo detecté.** Unión de viajes vigentes con partidas, agrupada por estatus.
- **Cómo afecta.** Sin filtrar por estatus: **+3,338 t** que nunca salieron de planta.
- **Qué hice.** Solo `TRA` y `ENT` (regla 2), filtrado en `int_viajes__embarcados`.

### H12 · El segmento de 13 clientes cambia durante el año

- **Qué vi.** 13 clientes cambian de segmento (95 tramos para 82 clientes). Cada versión de `vta_cliente` guarda el segmento vigente en ese momento.
- **Cómo lo detecté.** Historial por cliente con `lag(segmento)` tras normalizar el texto.
- **Cómo afecta.** Usar el segmento **actual** reasigna **3,336 t (7.1 %)** al segmento equivocado, por ejemplo 1,208 t de `DISTRIBUIDOR` pasarían a `CONSTRUCTORA`.
- **Qué hice.** `int_clientes__vigencia` construye tramos `[desde, hasta)` con la fecha del registro del cambio en **hora local de Monterrey** (ver H19). Prueba con los clientes 1002, 1055 y 1009 antes y después de su cambio, y unitarias para el borde.

### H13 · Clientes 9001, 9002 y 9003 no están en el maestro

- **Qué vi.** Las partidas traen 3 clientes que no existen en `vta_cliente` (82 partidas vigentes, 79 de ellas en viajes embarcados).
- **Cómo lo detecté.** `left join` de partidas contra el maestro y búsqueda de las que no encuentran cliente.
- **Cómo afecta.** Un `inner join` descartaría **983.19 t (2.09 % de lo embarcado)** y eliminaría la fila `NO_IDENTIFICADO`. Sobre el porcentaje global casi no influye (71.77 % en ambos casos): lo que se pierde son las toneladas.
- **Qué hice.** `left join` y la etiqueta `NO_IDENTIFICADO` (regla 7). Se distingue el motivo en `origen_segmento` (`CLIENTE_NO_EXISTE_EN_MAESTRO` vs `CLIENTE_DADO_DE_BAJA`). Prueba de conciliación contra un cálculo independiente.

---

## E. Revisiones entre versiones

### H15 · El costo del flete se revisa entre versiones

- **Qué vi.** El costo cambia en 177 viajes entre su primera y su última versión.
- **Cómo lo detecté.** Comparé el primer y el último `CostoFlete` no nulo de cada viaje.
- **Cómo afecta.** Con la versión vieja el flete sería 28,073,195 en vez de 28,421,590 MXN (**348 mil MXN, 1.2 %**).
- **Qué hice.** Última versión (ver H01). Las fechas de embarque pasan de nulas a capturadas cuando el viaje sale, pero una vez puestas, ni ellas, ni la planta, ni el compromiso cambian entre versiones; lo que se revisa es el costo, el peso y el POD.

### H16 · El peso documentado de las partidas se revisa entre versiones

- **Qué vi.** 103 partidas cambian de peso entre versiones.
- **Cómo afecta.** 3.06 t de diferencia en total. Es el efecto más pequeño, pero sigue siendo una cifra distinta en un tablero que "nunca cuadra".
- **Qué hice.** Última versión. **Peso por partida:** en cada viaje las partidas traen pesos casi iguales (por ejemplo 11,504 y 11,505 kg). Sospeché que era el total del viaje repetido, y lo **descarté**: la diferencia de 1 kg indica un reparto del total con redondeo, y el total por viaje va de 20,015 a 36,270 kg sin exceder nunca esa capacidad de camión. La suma por partidas es correcta.

---

## F. Preguntas abiertas y casos informativos

### H17 · Partidas con el mismo viaje, cliente, artículo y peso (abierto)

- **Qué vi.** En viajes embarcados hay 84 grupos (169 partidas) con el mismo viaje, cliente, artículo y peso, aunque con `IdPartida` distinto. Es una cantidad mucho mayor que la que daría el azar.
- **Cómo lo detecté.** `group by id_viaje, cla_cliente, cla_articulo, peso_kg having count(*) > 1`.
- **Cómo afecta.** Si fueran duplicados, habría hasta **796 t (1.7 %)** de sobreestimación.
- **Qué hice.** **No las eliminé.** No tengo evidencia que lo justifique: tienen `IdPartida` distinto, un cliente puede llevar dos partidas del mismo artículo y el total del viaje respeta la capacidad del camión. Lo dejo como observación abierta; la pregunta correcta es para el equipo del sistema origen.

### H18 · Viajes `ENT` sin POD, y un `TRA` con POD

- **Qué vi.** 25 viajes `ENT` (704 t) no tienen POD, porque Tráfico lo captura al recibir el documento físico. Hay además 36 `TRA` sin POD (normal) y 1 `TRA` con POD.
- **Cómo afecta.** Las toneladas sin POD no se pueden evaluar y quedan fuera de `cumplimiento_entrega`, como pide la regla 5.
- **Qué hice.** El viaje `TRA` con POD se considera entregado y evaluado (tiene POD, aunque el estatus no se haya actualizado). Es un **supuesto** documentado.

### H19 · Zona horaria del CDC (UTC) vs embarque (local)

- **Qué vi.** `_ab_cdc_updated_at` viene en UTC y las fechas de embarque en hora local.
- **Cómo lo detecté.** Convertí los 13 cambios de segmento a hora de Monterrey y comparé el día.
- **Cómo afecta.** **Cero cambios de día** en esta carga: no hay impacto hoy.
- **Qué hice.** Aun así implementé la conversión con el nombre de la zona (`America/Monterrey`) y no con "menos 6 horas", y la cubrí con una prueba unitaria (un cambio a las 05:30 UTC del 1 de marzo es el 28 de febrero en Monterrey). Así la protección queda probada aunque los datos actuales no la ejerciten.

---

## Diferencias entre la documentación y los datos

La documentación ayuda, pero no se debe dar por cierta sin revisar:

| Documentación | Realidad en los datos |
|---|---|
| `FechaRealEmbarque`: "Nulo si no se capturó" | Usa también `1900-01-01` como centinela (H05) |
| `Estatus`: `char(3)` con 4 valores | 20 variantes de mayúsculas y espacios (H04) |
| `Segmento`: `DISTRIBUIDOR`, `CONSTRUCTORA` o `INDUSTRIAL` | También `'Constructora '` y variantes (H14) |
| `IdViaje` (viaje y POD) y `ClaCliente` marcados como PK | No son únicos en landing: hay versiones (H01) |
| "Cada fila representa una versión" | Cierto, pero además hay copias exactas (H02) |
| "Fechas en hora local de planta (America/Monterrey)" | La planta de Houston (EE. UU.) no está en esa zona. **No lo pude verificar**: no hay una referencia independiente para comprobarlo |
| `ClaCliente` en partidas: "FK a `vta_cliente`" | 3 clientes no existen en el maestro (H13) |

**Sobre Houston.** Las fechas de embarque se usan tal cual vienen, sin conversión, y solo se toma el mes. Un viaje de Houston con una hora mal expresada podría cruzar un límite de mes, pero no hay evidencia en los datos de que ocurra. Queda como supuesto.

## Qué no cubrí

- **El camino "embarque anterior al primer registro del cliente"** (`PRIMER_SEGMENTO_CONOCIDO`) está implementado, pero **ningún dato real lo ejercita**. Lo cubre solo una prueba unitaria con datos inventados.
- **Una segunda carga** (`carga_2`). El proyecto lee `carga_*` y deduplica por LSN, pero no tengo datos para comprobar cómo se comporta con CDC incremental.
- **Cumplimiento por tonelada vs. por viaje.** Lo calculé en toneladas, como pide el contrato. Un indicador por número de viajes daría un resultado distinto y no lo incluí.
