# Alcance, estado y rendimiento del RAG

## Estado verificado

Medición del **19 de octubre de 2026, hora de Hermosillo** (20 de octubre en UTC).
Este es un registro de desarrollo, no una garantía para otras máquinas o futuros corpus.

| Elemento | Estado |
| --- | --- |
| PostgreSQL | Contenedor local saludable, puerto 5433, base `miuni_dev` |
| pgvector | 0.8.6 habilitado; índices HNSW coseno y GIN existentes |
| Esquema | Migraciones de MiUni.Api aplicadas; `documentofuente` y `rag_chunk` |
| Corpus validado | 488 documentos, 1,379 chunks después de consolidar duplicados |
| Contenido único por hash | 1,353 textos |
| Índice persistido | 488 documentos / 1,379 chunks con embeddings; cotejados contra los JSONL |
| Embeddings pendientes | Cero fragmentos faltantes o incompatibles con el corpus actual |
| Pruebas automatizadas | 21 pruebas aprobadas, incluidas consultas y transacciones PostgreSQL |
| Prueba con modelo real | Indexado, recuperación y reutilización de vectores comprobados |
| Activación local | `RAG_ENABLED=true`; reiniciar FastAPI para tomar el cambio |

El benchmark descrito abajo es histórico: se midió cuando solo había dos documentos
indexados. **No indexó documentos nuevos** ni realizó llamadas a Gemini. Después se
completó el indexado; sus 1,351 pendientes ya no describen el estado actual.

## Cuánto se estimó para el primer indexado

Se midió `BAAI/bge-m3` con PyTorch `2.14.1+cpu`, dos hilos de ejecución, sin CUDA,
con los pesos ya descargados. Después de calentar el modelo se tomaron dos textos
por rango de longitud, distribuidos dentro de cada rango. Se procesó cada pareja junta;
el batch configurado era 8, pero el batch efectivo de esta muestra fue 2.

| Longitud | Textos únicos pendientes | Palabras de las muestras | Segundos por texto en la muestra | Tiempo extrapolado |
| --- | ---: | --- | ---: | ---: |
| Menos de 175 palabras | 126 | 42, 144 | 2.670 | 5.6 min |
| De 175 a 349 palabras | 220 | 216, 300 | 7.443 | 27.3 min |
| 350 palabras o más | 1,005 | 463, 509 | 7.634 | 127.9 min |
| Total | 1,351 | 6 textos medidos | — | 160.8 min |

**Estimación central: 2 h 41 min de cálculo de embeddings. Para organizar el trabajo,
reservar aproximadamente 3–4 horas en esta CPU.** No es un intervalo estadístico ni
un tiempo máximo: una muestra pequeña, tokens distintos a palabras, batches por documento,
memoria, procesos concurrentes y rendimiento del disco pueden cambiar el resultado.
No se ha medido GPU; no hay una estimación verificada para CUDA.

El cálculo es la suma de `textos_pendientes_del_rango × segundos_por_texto_del_rango`.
No incluye SQL, carga/descarga inicial del modelo, scraping, descarga de PDFs ni extracción
del texto. Los JSONL actuales ya existen y los pesos ya están descargados en esta máquina.
Los pesos no se descargan otra vez por documento y la ingesta no llama a Gemini.

Para reproducir una estimación en otra computadora, después de preparar la base y los JSONL:

```powershell
.\venv\Scripts\python.exe scripts\benchmark_embeddings.py
```

El script consulta la caché de embeddings de PostgreSQL, muestrea solo contenidos
pendientes y guarda un reporte en `.cache/rag-benchmark.json`. No escribe en la base.
Se puede ampliar la muestra con `--samples-per-bucket 4`; esto tarda más, pero reduce
la dependencia de unos pocos ejemplos. La primera ejecución en una máquina nueva
puede descargar el modelo. Con caché completa, `HF_HUB_OFFLINE=1` permite medir sin
consultar Hugging Face; no activarlo antes de tener todos los archivos necesarios.

Para ejecutar el trabajo completo:

```powershell
.\venv\Scripts\python.exe scripts\index_embeddings.py
```

Cada documento confirmado imprime sus chunks, embeddings nuevos, vectores reutilizados,
chunks obsoletos eliminados y `elapsed_ms`. No ejecutar dos indexadores del mismo corpus
a la vez para intentar acelerarlo: compiten por recursos y los documentos se bloquean
por fuente para mantener consistencia.

Una segunda ejecución sin cambios reutiliza los vectores. No debería volver a costar
las mismas horas, aunque sigue leyendo archivos y actualizando metadata/filas.

## Cuánto tarda una pregunta del usuario

Indexar el corpus y contestar una pregunta son trabajos diferentes. El corpus se
embebe durante la ingesta; cada pregunta nueva necesita solo su propio embedding
(o el del pasaje HyDE). No se reembeben todos los documentos por pregunta.

En este benchmark:

- Primera frase, incluyendo importación/carga del modelo: **51.555 s**.
- Otra frase en el mismo proceso, modelo ya cargado: **0.478 s**.
- En la prueba anterior, la recuperación híbrida inicial tardó unos **40.3 s** con
  solo dos chunks en la base; la mayor parte estuvo en cargar/calcular el embedding.

Los 0.478 s **no son la latencia de una respuesta completa**, ni un promedio de muchas
consultas. A esa operación se suman HyDE si está activo, SQL vectorial/léxico, RRF,
rerank si está activo, Gemini y comunicación entre servicios. Cada arranque de
`search_rag.py` crea un proceso nuevo; FastAPI mantiene el modelo cargado entre consultas.

El modelo se carga de forma diferida: la primera consulta de cada proceso paga el
arranque. La inferencia local está protegida por un lock; varias preguntas simultáneas
pueden esperar turno. No se ha medido capacidad por segundo ni latencia p95 bajo carga.

## A qué nivel sirve en la arquitectura

El RAG es un **servicio de recuperación documental y generación de respuestas**:

1. El frontend envía la pregunta al backend .NET.
2. .NET valida la sesión, guarda historial y llama a FastAPI.
3. FastAPI genera HyDE opcionalmente, calcula el embedding local y consulta `rag_chunk`.
4. PostgreSQL devuelve candidatos por similitud y por texto; Python fusiona los rankings.
5. Se envían los fragmentos seleccionados y la pregunta a Gemini para redactar la respuesta.
6. .NET devuelve la respuesta a la interfaz y guarda el resultado en el historial.

PostgreSQL almacena/busca; BGE-M3 representa textos numéricamente; Gemini redacta.
Los embeddings se calculan localmente. La pregunta y los fragmentos elegidos pueden
salir a Gemini en las llamadas de generación: el sistema completo no funciona sin
servicios externos para responder en lenguaje natural.

El esquema SQL pertenece al backend .NET; Python indexa y consulta ese mismo esquema.
Docker proporciona la base reproducible. Actualmente Docker no empaqueta todos los servicios.

## Qué puede resolver

Cuando se cargue el corpus pertinente, sirve para preguntas sobre reglamentos,
trámites, requisitos, servicios y otra información universitaria presente en los
HTML/PDF indexados. Por ejemplo, explicar requisitos de titulación o localizar un
procedimiento documentado, citando la URL y las páginas de PDF cuando existan.

La rama densa ayuda a encontrar formulaciones similares en significado. La rama
léxica busca términos de la pregunta original. RRF combina los rankings; HyDE agrega
un pasaje hipotético para orientar la búsqueda vectorial. Ese pasaje no se usa como
evidencia para contestar. Los flags permiten comparar configuraciones.

Las instrucciones del chat piden reconocer cuando las fuentes no bastan y citar
enlaces. Eso es una guía al modelo: todavía no hay verificación automática de que
cada afirmación o cita esté respaldada por un fragmento.

## Qué no resuelve todavía

| Necesidad | Límite actual |
| --- | --- |
| Datos de todos los documentos | Están cargados los 488 documentos de los JSONL actuales; nuevas fuentes necesitan ingesta/indexado |
| Horarios/disponibilidad en tiempo real | Solo conoce el contenido guardado durante la ingesta; no consulta automáticamente el sitio en cada pregunta |
| Rutas del mapa, edificios o datos operativos de MiUni | La recuperación solo lee `rag_chunk`; no se conecta a las tablas operativas de campus ni ejecuta consultas de rutas |
| Información personal del estudiante | No consulta expediente, calificaciones, pagos ni sistemas escolares |
| Ejecutar trámites | Explica información; no inscribe, paga, modifica solicitudes ni realiza acciones administrativas |
| Memoria conversacional en el modelo | .NET guarda historial, pero el contrato actual envía a Python solamente `question`; no le pasa los mensajes previos |
| PDFs escaneados sin texto | La ingesta usa extracción textual; no hay etapa OCR implementada |
| Actualización automática del corpus | Scraping, extracción e indexado son comandos manuales; no hay calendario automático configurado |
| Garantía de exactitud/citas | No hay un conjunto de evaluación de dominio ni un validador de citas que demuestre un porcentaje de precisión |
| Capacidad de producción | No hay resultados de carga/concurrencia ni presupuesto de latencia medido con el corpus completo |

## Nivel de madurez y siguiente evaluación

**Prototipo funcional para integración y pruebas de un MVP documental.** Las pruebas
automatizadas comprueban comportamiento del software, no que el asistente conteste
correctamente todas las preguntas universitarias. Todavía no se ha validado como
servicio de producción ni ejecutado un benchmark de respuestas completas con Gemini.
El reranker está implementado y desactivado; sus pesos y calidad no se han probado aquí.

Para evaluar el MVP con el equipo:

1. Usar el índice completo local y acordar qué fuentes cubren la primera versión.
2. Preparar preguntas reales con fuentes/respuestas esperadas, incluyendo preguntas
   sin respuesta en el corpus y preguntas ambiguas.
3. Comparar vectorial, híbrida y híbrida+HyDE con las mismas preguntas; medir si las
   fuentes esperadas aparecen entre los primeros resultados y si las citas son correctas.
4. Medir primera consulta y consultas calientes por separado, incluyendo latencia de
   Gemini y casos concurrentes; registrar mediana y p95.
5. Probar rerank solo después de tener una referencia para decidir si su mejora compensa
   el tiempo adicional.
