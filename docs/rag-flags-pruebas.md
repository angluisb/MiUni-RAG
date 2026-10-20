# Probar el RAG y entender sus flags

## Estado comprobado en esta máquina

El 19 de octubre de 2026 se compararon los JSONL con PostgreSQL: **488 documentos,
1379 fragmentos y 1379 embeddings**, sin fragmentos faltantes ni vectores incompatibles
con el modelo y versión actuales. Son los documentos de este corpus, no todos los
documentos existentes de la universidad. El `.env` local tiene `RAG_ENABLED=true`.
La plantilla conserva `false` para que una instalación nueva prepare su índice primero.

No necesitas generar otra vez los embeddings para hacer preguntas. El índice se
guarda en el volumen de PostgreSQL; la caché de BGE-M3 se guarda en `.cache/huggingface`.
Reiniciar FastAPI vuelve a cargar el modelo en memoria, pero no recalcula el corpus.

## Pruebas, de menor a mayor alcance

Desde `C:\Dev\python\rag-miuni`, con Docker Desktop y la base encendidos:

```powershell
.\venv\Scripts\python.exe scripts\index_embeddings.py --check-db
.\venv\Scripts\python.exe scripts\search_rag.py 'Abogacia General' --mode lexical
.\venv\Scripts\python.exe scripts\search_rag.py 'Para que sirve la Oficina de la Abogacia General?' --mode hybrid
```

1. `--check-db` comprueba extensión, columnas, índices y conteos; no genera embeddings.
2. `lexical` busca palabras en PostgreSQL; no necesita BGE-M3 ni API key.
3. `hybrid` combina vectores y palabras; necesita BGE-M3, pero no API key sin `--hyde`.

Los resultados de búsqueda son fragmentos y fuentes, no una respuesta redactada.
Revisa que sus textos contesten la pregunta. La primera consulta en un proceso puede
tardar bastante al cargar BGE-M3. Cada comando CLI inicia un proceso diferente;
FastAPI conserva el modelo cargado entre preguntas.

Para una respuesta completa:

```powershell
.\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Abre `http://127.0.0.1:8000/docs`, selecciona **POST /api/v1/chat → Try it out** y envía:

```json
{"question":"¿Para qué sirve la Oficina de la Abogacía General?"}
```

También puedes hacerlo desde otra terminal:

```powershell
$body = @{ question = 'Para que sirve la Oficina de la Abogacia General?' } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/chat -Method Post -ContentType 'application/json' -Body $body
```

Espera HTTP 200 y los campos `query` y `answer`. El chat necesita una `API_KEY` válida,
acceso a Gemini y cuota disponible. Verifica que las citas correspondan al contenido:
recuperar ocho fragmentos no garantiza que todos sean relevantes ni que la respuesta
sea correcta. El endpoint `/api/v1/chat/stream` ofrece la respuesta por streaming.

## Ajustes del archivo .env

Un flag booleano acepta `true` o `false`. Los valores de la tabla son los defaults del
código; tu `.env` o variables del proceso pueden cambiarlos. **Reinicia FastAPI después
de editar `.env`**. Las variables del proceso tienen prioridad.

### Conexión y generación

| Variable | Default | Qué hace |
| --- | --- | --- |
| `API_KEY` | Vacío | Clave de Google GenAI para la respuesta final y HyDE. No se usa para calcular embeddings locales. |
| `LLM_MODEL` | `gemini-3.1-flash-lite` | Modelo que redacta la respuesta y el pasaje HyDE. Debe estar disponible para tu cuenta. |
| `DATABASE_URL` | Vacío | Conexión PostgreSQL. Obligatoria para indexar o recuperar documentos; usa la contraseña real del `.env` de MiUni. |
| `RAG_ENABLED` | `false` | En `true`, los endpoints del chat recuperan documentos antes de responder. En `false`, el chat llama al LLM sin contexto documental. No apaga los scripts CLI de búsqueda/indexado. |
| `RAG_DB_CONNECT_TIMEOUT_SECONDS` | `5` | Tiempo máximo de conexión a PostgreSQL, en segundos. |
| `RAG_DB_STATEMENT_TIMEOUT_MS` | `30000` | Tiempo máximo por sentencia SQL, en milisegundos. |

### Modelo de embeddings

| Variable | Default | Qué hace |
| --- | --- | --- |
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-m3` | Modelo local de vectores. Actualmente el código solo acepta este valor. |
| `RAG_EMBEDDING_DIMENSION` | `1024` | Tamaño del vector; actualmente solo se acepta 1024, igual que la columna SQL. |
| `RAG_EMBEDDING_BATCH_SIZE` | `8` | Textos procesados juntos, de 1 a 128. Bajar a 2 o 1 si falta RAM durante el indexado. No equivale a usuarios simultáneos. |
| `RAG_MODEL_DEVICE` | `cpu` | Dispositivo de inferencia. `cuda` requiere GPU y PyTorch compatibles; cambiarlo no instala soporte GPU. |
| `RAG_MODEL_CACHE` | `.cache/huggingface` del proyecto | Carpeta de pesos del modelo. Se puede usar una ruta absoluta a una caché completa copiada por el equipo. |
| `RAG_EMBEDDING_PIPELINE_VERSION` | `rag-embeddings-v1` | Identifica cómo se preparó el texto para embebido. Cambiarla invalida la compatibilidad de los embeddings anteriores: reindexar todo antes de servir consultas. |

### Recuperación y calidad

| Variable | Default | Qué hace |
| --- | --- | --- |
| `RAG_HYBRID_SEARCH_ENABLED` | `true` | Combina búsqueda vectorial y búsqueda por palabras usando RRF. En `false`, el chat usa solo vectores; no significa “solo palabras”. |
| `RAG_HYDE_ENABLED` | `true` | Pide al LLM un pasaje hipotético y lo usa para buscar vectores. Agrega una llamada al modelo. Si falla, busca con la pregunta original. La búsqueda léxica siempre usa la pregunta original. |
| `RAG_HYDE_SENTENCES` | `3` | Número de oraciones pedido en el prompt HyDE, de 2 a 4. Es una instrucción al modelo, no un validador de su salida. |
| `RAG_HYDE_TIMEOUT_SECONDS` | `15` | Espera máxima para HyDE; después continúa con la pregunta original. No limita la respuesta final del chat. |
| `RAG_VECTOR_TOP_N` | `30` | Candidatos de la rama vectorial, de 1 a 500. |
| `RAG_LEXICAL_TOP_N` | `30` | Candidatos de la rama léxica, de 1 a 500. Solo se usa en búsqueda híbrida. |
| `RAG_RRF_K` | `60` | Constante para fusionar rankings: suma `1 / (k + posición)` por rama. No es la cantidad de resultados. |
| `RAG_CONTEXT_TOP_K` | `8` | Máximo de fragmentos enviados al LLM, de 1 a 100. Más fragmentos aumentan el contexto y pueden agregar ruido/coste. |
| `RAG_RERANK_ENABLED` | `false` | Activa un segundo modelo local que reordena candidatos antes de seleccionar el contexto. Descarga pesos adicionales y consume RAM/tiempo. |
| `RAG_RERANK_PROVIDER` | `local_bge` | Único proveedor de reranking implementado. No hay proveedor remoto configurado. |
| `RAG_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | Modelo del reranker; solo se carga si se activa el reranking. |

Cambiar HyDE, búsqueda híbrida, rerank o cantidades de candidatos **no requiere
regenerar embeddings del corpus**. Cambiar el modelo/dimensión requiere adaptar código,
esquema e índice; no basta con escribir otro nombre en `.env`.

Para comparar en esta laptop, empieza con híbrido sin HyDE ni rerank; luego activa
HyDE y evalúa las mismas preguntas. Así puedes medir si mejora las fuentes y cuánto
tiempo agrega. Esto es una configuración de prueba, no una garantía de mayor precisión:

```dotenv
RAG_ENABLED=true
RAG_HYBRID_SEARCH_ENABLED=true
RAG_HYDE_ENABLED=false
RAG_RERANK_ENABLED=false
```

### Medición y logs

| Variable | Default | Qué hace |
| --- | --- | --- |
| `RAG_MEASURE_RETRIEVAL_PERFORMANCE` | `true` | Publica en logs tiempos por etapa, flags, IDs y URLs recuperadas. Las métricas internas siguen calculándose aunque se desactive su publicación. |
| `RAG_EXPERIMENT_NAME` | `hyde_hybrid_v1` | Etiqueta libre en las métricas para comparar experimentos. No cambia el algoritmo. |
| `RAG_LOG_RETRIEVAL_RESULTS` | `false` | Escribe IDs, puntuaciones y URLs en los logs. |
| `RAG_LOG_CONTEXT_CHUNKS` | `false` | Escribe el texto completo recuperado. Úsalo solo cuando necesites depurar el contexto. |

`total_retrieval_ms` mide la recuperación, incluyendo HyDE si se usa. **No incluye**
la generación de la respuesta final. Compara primeras consultas por separado de
consultas con el modelo ya cargado.

## Flags de los comandos

### scripts/index_embeddings.py

| Flag | Uso |
| --- | --- |
| Sin flags | Lee los JSONL HTML/PDF existentes y actualiza el índice. Reutiliza vectores compatibles; no necesita API key. |
| `--check-db` | Comprueba la base y termina; tiene prioridad sobre las opciones de indexado. |
| `--dry-run` | Valida y cuenta JSONL sin conectar a la base ni cargar/descargar BGE-M3. |
| `--input ARCHIVO [ARCHIVO ...]` | Selecciona JSONL. Cada fuente incluida debe tener todos sus fragmentos, porque los anteriores que ya no aparezcan se eliminan para esa fuente. |
| `--limit-documents 2` | Procesa los primeros dos documentos completos, no dos fragmentos. Debe ser positivo. |

Si ya tienes los 1379 embeddings compatibles, usa `--check-db` y las búsquedas.
El indexado solo hace falta cuando agregues/cambies documentos o restaures desde JSONL.
La reejecución sin cambios reutiliza vectores, aunque sigue actualizando filas/metadata.

### scripts/search_rag.py

| Argumento/flag | Uso |
| --- | --- |
| `"pregunta"` | Texto obligatorio y no vacío. Ponerlo entre comillas si contiene espacios. |
| `--mode hybrid` | Default del CLI: vectores + palabras + RRF. |
| `--mode vector` | Solo búsqueda vectorial. |
| `--mode lexical` | Solo palabras; no carga BGE-M3 ni aplica rerank. Usa `RAG_CONTEXT_TOP_K` como límite. |
| `--hyde` | Activa HyDE para esta ejecución; requiere API key. No se acepta junto con `--mode lexical`. |

**El CLI no activa HyDE si no pasas `--hyde`, aunque `.env` tenga
`RAG_HYDE_ENABLED=true`.** Su `--mode` también prevalece sobre el flag híbrido del
archivo. Los endpoints del chat sí respetan ambos flags del `.env`.

### scripts/benchmark_embeddings.py

| Flag | Uso |
| --- | --- |
| `--samples-per-bucket 2` | Cantidad de muestras por grupo de longitud, default 2. Aumentarla hace una medición más larga. |
| `--output RUTA` | Destino JSON del informe; default `.cache/rag-benchmark.json`. Reemplaza ese informe si ya existe. |

Este script estima indexado pendiente con una muestra; no escribe vectores en PostgreSQL.
Si todo está indexado, reporta cero pendientes y no necesita cargar el modelo.
`HF_HUB_OFFLINE=1` es una variable de Hugging Face, no un flag propio: usarla solo
cuando la caché esté completa para evitar consultas de descarga.

## Comandos del equipo en MiUni

Desde la raíz del repositorio **MiUni**, el helper es:

```powershell
powershell -NoProfile -File .\scripts\dev.ps1 -Action check
```

| `-Action` | Función |
| --- | --- |
| `init` | Crea `.env` con contraseña PostgreSQL y clave JWT aleatorias. Solo para instalación nueva; no sobrescribe un `.env` existente. |
| `check` | Valida configuración sin mostrar secretos ni conectar a la base. |
| `migrate` | Carga `.env`, selecciona ambiente Docker y aplica migraciones EF. |
| `api` | Carga configuración e inicia backend en `localhost:5124`. |

`-EnvPath RUTA` permite elegir otro archivo de configuración; normalmente se omite.
La [guía para principiantes](guia-docker-rag-equipo.md) explica la instalación local.
