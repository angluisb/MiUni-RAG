# MiUni RAG

Servicio FastAPI para el chatbot institucional de MiUni: ingesta HTML/PDF, embeddings BGE-M3,
busqueda hibrida con PostgreSQL/pgvector, HyDE, RRF y rerank opcional.

Para preparar una máquina del equipo desde cero, consultar la
[guía paso a paso de Docker, backend, frontend y RAG](docs/guia-docker-rag-equipo.md).
El [alcance y rendimiento del RAG](docs/rag-alcance-rendimiento.md) explica qué resuelve,
sus límites y la estimación medida del indexado completo.
La [referencia de flags y pruebas](docs/rag-flags-pruebas.md) explica cada opción
y cómo probar los 488 documentos ya indexados en esta máquina.
La [medición del streaming](docs/medicion-streaming.md) documenta el flujo de la
interfaz y el comando para medir primer texto y respuesta completa.

## Configuracion

Crea un archivo local `.env` a partir del ejemplo solo si no existe:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Luego configura:

```text
API_KEY=tu_google_genai_api_key
DATABASE_URL=postgresql://USUARIO:CLAVE@127.0.0.1:5433/miuni_dev
```

Sustituye los marcadores de la conexión por los valores privados del `.env` de MiUni.
No hay contraseña por defecto en el código. No publiques ninguno de los dos `.env`.

## Ejecutar La API

```powershell
uvicorn app:app --host 127.0.0.1 --port 8000
```

Endpoints del chat:

```text
POST /api/v1/chat
POST /api/v1/chat/stream
```

## Pipeline De Scraping Web Para RAG

El contrato de scraping esta documentado en:

```text
docs/rag-web-scraping.md
```

El contrato inicial para descarga de PDFs esta documentado en:

```text
docs/rag-pdf-download.md
```

El plan inicial para embeddings y busqueda hibrida esta documentado en:

```text
docs/rag-embeddings-hybrid-search.md
```

Las URLs semilla versionadas estan en:

```text
data/sources/web_seed_urls.json
```

Los datos generados se ignoran intencionalmente en Git:

```text
data/raw/
data/processed/
data/sources/discovered_pages.json
data/sources/discovered_pdfs.json
```

Esto mantiene el repositorio enfocado en scripts, contratos de fuentes y configuracion reproducible.

### 1. Descubrir Paginas HTML Y PDFs

```powershell
python scripts\scrape_web.py --max-depth 2 --max-pages 20 --delay 0.2
```

Este comando genera:

```text
data/sources/discovered_pages.json
data/sources/discovered_pdfs.json
data/raw/html/
data/raw/html/metadata.json
```

### 2. Generar Chunks HTML

```powershell
python scripts\ingest_html.py
```

Este comando genera:

```text
data/processed/chunks/html_chunks.jsonl
```

### 3. Inspeccionar Chunks

```powershell
$env:PYTHONIOENCODING='utf-8'; python scripts\inspect_chunks.py --sample 3
```

Usa este comando para revisar conteos, categorias, dominios, chunks cortos y muestras de contenido antes de generar embeddings.

### 4. Descargar PDFs Descubiertos

```powershell
python scripts\download_pdfs.py --max-pdfs 200 --delay 0.1 --timeout 20
```

Este comando genera:

```text
data/raw/pdfs/
data/raw/pdfs/metadata.json
```

Por defecto salta PDFs que parecen CVs o documentos personales.

### 5. Generar Chunks PDF

```powershell
python scripts\ingest_pdf.py
```

Este comando genera:

```text
data/processed/chunks/pdf_chunks.jsonl
```

## Flujo Esperado

```text
web_seed_urls.json
  -> scrape_web.py
  -> discovered_pages.json / discovered_pdfs.json / data/raw/html/
  -> ingest_html.py
  -> html_chunks.jsonl
  -> download_pdfs.py
  -> data/raw/pdfs/
  -> ingest_pdf.py
  -> pdf_chunks.jsonl
  -> inspect_chunks.py
```

Los chunks HTML y PDF usan `512` palabras maximo, overlap de `100` palabras y minimo deseado de `175` palabras.

## PostgreSQL y pgvector compartidos con MiUni

El backend en `C:\Dev\miuni\MiUni` ya define la imagen PostgreSQL 16 con pgvector,
PostGIS y pgRouting. No se necesita otro contenedor ni compilar pgvector en Windows.
La conexion desde Python en Windows es `127.0.0.1:5433`, base `miuni_dev`.
Dentro de una misma red Docker se usaria `db:5432`.

```powershell
cd C:\Dev\miuni\MiUni
powershell -NoProfile -File .\scripts\dev.ps1 -Action check
docker compose up -d db
powershell -NoProfile -File .\scripts\dev.ps1 -Action migrate
```

Docker Desktop debe estar instalado y abierto si usas esa base local. Para una
instalación nueva, ejecuta primero el helper con `-Action init`; genera claves
aleatorias. .NET recibe conexión y JWT desde `.env` usando el helper, no desde JSON.

La migracion `20261006162727_AddRagChunksPgvector` es la propietaria del esquema:
`documentofuente` y `rag_chunk` (singular), con UUID, `embedding vector(1024)`,
`search_tsv` generado en espanol, indice HNSW coseno e indice GIN.
Python usa esas tablas directamente; no crea una tabla paralela `rag_chunks`.
Ejecuta las migraciones con compilacion para incluir cambios nuevos; `--no-build`
solo sirve si el ensamblado ya contiene la migracion.

Si el volumen existia antes de agregar pgvector, los scripts de init de Docker no
se vuelven a ejecutar. La imagen debe incluir la extension y la migracion del backend
la habilita en la base correspondiente. No borres el volumen para resolverlo.

## Indexar y consultar

Desde este repositorio, con Python 3.12 y el entorno virtual:

Si ya tienes el índice completo, basta con `--check-db` y las búsquedas.
No necesitas repetir el indexado.

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-rag.txt
.\venv\Scripts\python.exe scripts\index_embeddings.py --check-db
.\venv\Scripts\python.exe scripts\index_embeddings.py --dry-run
.\venv\Scripts\python.exe scripts\index_embeddings.py
```

El modelo `BAAI/bge-m3` se descarga la primera vez a `.cache/huggingface` (varios GB).
Se ejecuta en CPU por defecto. Para GPU instala PyTorch compatible y configura
`RAG_MODEL_DEVICE=cuda`. `RAG_EMBEDDING_BATCH_SIZE` controla el uso de memoria.
No necesitas API_KEY para indexar ni buscar sin HyDE.

El indexador lee ambos JSONL existentes por defecto. Puedes pasar
`--input data/processed/chunks/html_chunks.jsonl` o `--limit-documents 2`
para una prueba pequena. Cada documento suministrado debe estar completo:
se actualiza por `(source_url, chunk_index)` y se eliminan sus chunks obsoletos
dentro de la misma transaccion. Las fuentes ausentes del archivo no se eliminan.
Entradas repetidas con el mismo texto se consolidan y sus categorias se conservan
en `metadata.source_categories`; textos contradictorios para la misma URL/indice fallan.

El UUID es estable por URL/indice y el ID del JSONL se conserva en `metadata.chunk_id`.
Los embeddings se reutilizan por SHA-256 del contenido, modelo, dimension y version
del pipeline, incluso entre fuentes. La metadata se refresca aunque se reutilice el
vector. El texto embebido es exactamente `content`; cambios solo de titulo o metadata
no necesitan reembedding. Si cambia esa estrategia, cambia `RAG_EMBEDDING_PIPELINE_VERSION`
y reindexa todo antes de volver a servir consultas.

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\venv\Scripts\python.exe scripts\search_rag.py 'requisitos de titulacion' --mode lexical
.\venv\Scripts\python.exe scripts\search_rag.py 'Como puedo titularme?' --mode vector
.\venv\Scripts\python.exe scripts\search_rag.py 'Como puedo titularme?'
.\venv\Scripts\python.exe scripts\search_rag.py 'Como puedo titularme?' --hyde
```

En `.env`, configura `DATABASE_URL` y activa `RAG_ENABLED=true` despues de indexar.
Con `RAG_ENABLED=false` se mantiene el chat anterior sin acceso a base ni modelos locales.
Ambos endpoints existentes usan el contexto recuperado cuando se activa; se mantienen
el JSON `{query, answer}` y el streaming de texto que consume MiUni.Api.
La respuesta recibe fuentes con URL y paginas de PDF para citarlas.

## Flags y medicion

`.env.example` contiene todas las opciones. `RAG_HYBRID_SEARCH_ENABLED=false` usa
solo recuperacion densa. `RAG_HYDE_ENABLED=false` embebe la pregunta directamente.
Con HyDE activo, solo la rama vectorial usa el pasaje hipotetico; la busqueda lexica
siempre usa la pregunta original. Un error, timeout o respuesta vacia de HyDE vuelve
a la pregunta original. El pasaje hipotetico nunca se envia como evidencia al chat.

RRF fusiona ambos rankings antes de tomar `RAG_CONTEXT_TOP_K`. El rerank local con
`BAAI/bge-reranker-v2-m3` se activa con `RAG_RERANK_ENABLED=true`, descarga otro modelo
y procesa todos los candidatos fusionados antes del corte final. Esta apagado por defecto.

`RAG_MEASURE_RETRIEVAL_PERFORMANCE=true` registra un evento JSON `rag_retrieval` por
consulta con identificador, experimento, tiempos por etapa, fuentes e IDs devueltos.
Los tiempos incluyen carga inicial del modelo en la primera consulta. Los flags
`RAG_LOG_RETRIEVAL_RESULTS` y `RAG_LOG_CONTEXT_CHUNKS` permiten detalle adicional;
el segundo incluye el texto de las fuentes y esta apagado por defecto.
Un fallo de base o embeddings se propaga como error; no se responde silenciosamente
sin evidencia. El streaming comprueba la recuperacion y el primer token antes de emitir HTTP 200.

## Pruebas

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
$env:RUN_RAG_DB_TESTS = '1'
.\venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:RUN_RAG_DB_TESTS
```

Las pruebas PostgreSQL requieren la migracion aplicada y usan tablas temporales
copiadas del esquema real, sin modificar los documentos indexados. Comprueban
reindexado, cache, poda por fuente, rollback y busqueda vectorial/lexica.
Las pruebas unitarias cubren RRF, HyDE, flags, contexto y compatibilidad del chat;
no descargan modelos ni hacen llamadas a Gemini.
