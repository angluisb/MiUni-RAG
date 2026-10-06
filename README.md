# MiUni RAG

Servicio FastAPI para el chatbot institucional de MiUni y utilidades de ingest para el futuro flujo RAG.

## Configuracion

Crea un archivo local `.env` a partir del ejemplo:

```powershell
Copy-Item .env.example .env
```

Luego configura:

```text
API_KEY=tu_google_genai_api_key
```

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
