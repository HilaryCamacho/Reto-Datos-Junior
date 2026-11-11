# Reto — Ingeniero(a) de Datos Junior · Grupo DEACERO

## Antes de empezar

- **Qué hay en esta carpeta:** este `README.md` (las instrucciones), `docs/` (la documentación del negocio y del sistema origen) y `data/replica/carga_1/` (los datos, en CSV).
- **Los datos son ficticios.** Se generaron para este reto: no corresponden a clientes, operaciones ni cifras reales.
- **Plazo: 7 días naturales (1 semana)**, contados a partir del día en que recibes este archivo. Es el tiempo máximo para enviar el link de tu repositorio. Dedicación esperada: alrededor de **8 a 12 horas**.
- **Qué necesitas:** una computadora con Python 3.9 o superior, Git y una cuenta de GitHub. Todo lo demás es gratis y se instala desde Python.
- **Cómo entregas:** responde al correo con el que recibiste este archivo con el **link a tu repositorio público**. Solo el link: no adjuntes archivos.
- **No hay canal de dudas, a propósito.** Si algo es ambiguo, toma la decisión que te parezca más razonable, escríbela en una sección **Supuestos** de tu `README.md` y sigue adelante. Cómo resuelves la ambigüedad también es parte de la evaluación.

## El problema

Replicamos los sistemas operativos de la empresa a la nube. Los datos llegan tal cual salen del origen: en texto, con historia de cambios y con detalles que nadie documentó. El área de Logística necesita un tablero confiable, y para eso necesita datos limpios y bien modelados.

## Lo que queremos

Lleva los datos replicados hasta **las dos tablas** que necesita Logística, y cuéntanos qué encontraste en el camino.

No buscamos que lo sepas todo. Buscamos ver **cómo piensas**: cómo revisas datos que no conoces, cómo traduces una regla de negocio a código, cómo compruebas que tu resultado es correcto y qué se te ocurre hacer más allá de lo que te pidieron.

## El material

- En `data/replica/carga_1/` hay cinco tablas de fletes, clientes y plantas, replicadas desde SQL Server con **Airbyte CDC**. Todas las columnas vienen en texto.
- En `docs/` está lo que nos dieron el negocio y los equipos del origen: el requerimiento, un diccionario de datos, el contrato de las tablas finales y nuestras convenciones. Úsalos como usarías documentación real: ayudan, pero no los des por ciertos sin revisarlos.

## Qué tienes que entregar

1. **Las dos tablas** de `docs/contrato-marts.md` (`embarques_mensual` y `cumplimiento_entrega`) en el esquema `mart_logistica` de un archivo `deacero.duckdb`, siguiendo las reglas de `docs/requerimiento-negocio.md`.
2. **Que se pueda correr dos veces** sin que nada se duplique.
3. **Al menos dos pruebas automáticas** que revisen una regla de negocio del requerimiento (no solo que una columna no venga vacía). Una buena prueba es la que **fallaría** si el cálculo estuviera mal.
4. **`HALLAZGOS.md`**: los problemas que encontraste en los datos. Para cada uno: qué viste, cómo lo detectaste, cómo afecta al resultado y qué hiciste con él.
5. **`README.md`**: cómo correrlo paso a paso, qué decisiones tomaste y por qué, y qué dejaste fuera.
6. **Tu toque:** algo que no te pedimos y que creas que aporta valor. Puede ser cualquier cosa: una visualización, un reporte de calidad de datos, una forma más fácil de correrlo, un script que perfile tablas, una propuesta de mejora. Explícanos por qué lo elegiste.

## Herramientas

- Te recomendamos **dbt con DuckDB** (es gratis y corre en tu computadora). Si no los conoces, es buena oportunidad para aprender lo básico; si prefieres SQL y Python, también se vale: explica por qué.
- Todo debe correr en local, sin costo y sin credenciales.
- Usa IA todo lo que quieras, pero **entiende lo que entregas**: en la sesión te vamos a preguntar por qué hiciste cada cosa.

## Cómo lo vamos a evaluar

1. Seguimos tu README, lo corremos **dos veces** y comparamos tus tablas contra los resultados esperados.
2. Leemos tu `HALLAZGOS.md`, tus pruebas y tu código.
3. **Sesión en vivo de 60 minutos:** nos explicas tu solución y después revisamos juntos una tabla nueva que nunca has visto. Ahí no esperamos que sepas la respuesta: queremos ver cómo la buscas. Puedes usar tus herramientas.

## Entrega

- **Plazo: 7 días naturales (1 semana)** desde que recibiste este archivo.
- Un repositorio **público** en tu GitHub con todo lo anterior (el link se entrega como dice *Antes de empezar*). Si no te alcanza el tiempo, entrega menos pero bien hecho, y dinos qué faltó: eso también cuenta a tu favor.
- El historial de git cuenta: haz commits a medida que avances.
- Cero secretos en el repositorio.

