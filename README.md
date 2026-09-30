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

## Flujo Esperado

```text
web_seed_urls.json
  -> scrape_web.py
  -> discovered_pages.json / discovered_pdfs.json / data/raw/html/
  -> ingest_html.py
  -> html_chunks.jsonl
  -> inspect_chunks.py
```

Los PDFs descubiertos no se procesan en este flujo. Quedan registrados para que el pipeline de PDFs los descargue, extraiga texto y genere `pdf_chunks.jsonl`.
