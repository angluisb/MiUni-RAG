# MiUni RAG

FastAPI service for the MiUni institutional chatbot and RAG ingestion utilities.

## Environment

Create a local `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

Then set:

```text
API_KEY=your_google_genai_api_key
```

## Run The API

```powershell
uvicorn app:app --host 127.0.0.1 --port 8000
```

The chat endpoints are:

```text
POST /api/v1/chat
POST /api/v1/chat/stream
```

## RAG Web Scraping Pipeline

The scraping contract is documented in:

```text
docs/rag-web-scraping.md
```

The seed URLs are versioned in:

```text
data/sources/web_seed_urls.json
```

Generated data is intentionally ignored by Git:

```text
data/raw/
data/processed/
data/sources/discovered_pages.json
data/sources/discovered_pdfs.json
```

This keeps the repository focused on scripts, source contracts, and reproducible configuration.

### 1. Discover HTML Pages And PDFs

```powershell
python scripts\scrape_web.py --max-depth 2 --max-pages 20 --delay 0.2
```

This generates:

```text
data/sources/discovered_pages.json
data/sources/discovered_pdfs.json
data/raw/html/
data/raw/html/metadata.json
```

### 2. Generate HTML Chunks

```powershell
python scripts\ingest_html.py
```

This generates:

```text
data/processed/chunks/html_chunks.jsonl
```

### 3. Inspect Chunks

```powershell
$env:PYTHONIOENCODING='utf-8'; python scripts\inspect_chunks.py --sample 3
```

Use this to review chunk counts, categories, domains, short chunks, and sample content before generating embeddings.
