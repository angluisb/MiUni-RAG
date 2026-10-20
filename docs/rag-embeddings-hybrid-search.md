# Plan de Embeddings y Busqueda Hibrida para RAG

## Implementacion

El pipeline esta implementado en `app/rag/`, `scripts/index_embeddings.py` y
`scripts/search_rag.py`. La configuracion y los comandos estan en `README.md`.
El esquema real se reutiliza de la migracion `AddRagChunksPgvector` de MiUni.Api:
la tabla se llama **rag_chunk** y tiene FK a **documentofuente**. Los IDs SQL son
UUID; los IDs legibles del JSONL quedan en `metadata.chunk_id`.
El esquema conceptual de abajo es una referencia del plan, no una segunda tabla.
`RAG_ENABLED` permite activar el contexto en ambos endpoints despues de indexar.

Referencias de implementacion:
- [BGE-M3](https://huggingface.co/BAAI/bge-m3)
- [pgvector: coseno, HNSW y filtros](https://github.com/pgvector/pgvector)
- [SentenceTransformer.encode](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)
- [Psycopg: conexiones y transacciones](https://www.psycopg.org/psycopg3/docs/basic/usage.html)

## Proposito

Este documento define el plan inicial para indexar chunks HTML/PDF y recuperar contexto para el chatbot de MiUni.

## Modelo de embeddings

Modelo propuesto:

```text
BAAI/bge-m3
```

Razones:

- Es multilingue.
- Funciona bien para espanol e ingles.
- Soporta recuperacion densa, sparse/lexical weights y multi-vector en su implementacion completa.
- Tiene dimension densa de `1024`.
- Puede correrse localmente con Python usando `sentence-transformers` o `FlagEmbedding`.

Uso inicial recomendado:

```text
embedding_mode = dense
embedding_dimension = 1024
```

Despues se puede evaluar si conviene usar tambien las salidas sparse/ColBERT de BGE-M3. Para el primer pipeline basta con dense embeddings + busqueda lexica de Postgres.

## Chunking esperado

Parametros objetivo para HTML y PDF:

```text
max_words = 512
min_words = 175
overlap_words = 100
overlap_percent_aprox = 19.5%
strategy = paragraph_sliding_window
```

Reglas:

- `512` palabras es el maximo por chunk.
- `175` palabras es el minimo deseado.
- El overlap debe mantenerse entre 10% y 25%.
- El corte debe hacerse por parrafos cuando sea posible.
- Si un parrafo excede `512` palabras, se corta por ventana deslizante de palabras.
- El overlap solo aplica entre chunks consecutivos del mismo documento.
- No se debe mezclar contenido de documentos distintos.

## Metadata de cada chunk

Campos principales:

```json
{
  "id": "serviciosescolares-unison-mx-requisitos-de-titulacion-0000",
  "source_type": "html",
  "source_url": "https://serviciosescolares.unison.mx/requisitos-de-titulacion/",
  "document_title": "Requisitos de Titulacion",
  "category": "tramites",
  "chunk_index": 0,
  "content": "Texto limpio del chunk..."
}
```

Metadata comun:

```json
{
  "institution": "Universidad de Sonora",
  "domain": "serviciosescolares.unison.mx",
  "section": "tramites",
  "last_seen_at": "2026-10-06",
  "content_word_count": 312,
  "content_sha256": "hash-del-contenido",
  "chunking_strategy": "paragraph_sliding_window",
  "chunk_max_words": 512,
  "chunk_overlap_words": 100,
  "chunk_min_words": 175
}
```

Metadata adicional para HTML:

```json
{
  "raw_html_path": "data/raw/html/serviciosescolares-unison-mx-....html"
}
```

Metadata adicional para PDF:

```json
{
  "raw_pdf_path": "data/raw/pdfs/reglamento-escolar-....pdf",
  "pdf_sha256": "hash-del-pdf",
  "page_start": 1,
  "page_end": 2,
  "last_downloaded_at": "2026-10-06"
}
```

Metadata de indexado, una vez generado el embedding:

```json
{
  "embedding_model": "BAAI/bge-m3",
  "embedding_dimension": 1024,
  "embedding_created_at": "2026-10-06T00:00:00Z",
  "embedding_input_sha256": "hash-del-texto-embeddeado",
  "embedding_pipeline_version": "rag-embeddings-v1"
}
```

## Esquema conceptual de indexado

Tabla conceptual de chunks:

```text
rag_chunks
  id
  source_type
  source_url
  document_title
  category
  chunk_index
  content
  metadata jsonb
  embedding vector(1024)
  search_tsv tsvector
  created_at
  updated_at
```

Indices esperados:

```text
embedding -> pgvector ivfflat o hnsw
search_tsv -> GIN
source_url + chunk_index -> unique
content_sha256 -> index para evitar re-embed innecesario
```

## Busqueda hibrida con HyDE

Flujo objetivo:

1. El usuario hace una pregunta.
2. El LLM genera una respuesta hipotetica corta de 2 a 4 oraciones.
3. Se calcula el embedding de esa respuesta hipotetica.
4. Rama vectorial: top-N por similitud coseno con ese embedding.
5. Rama lexica: top-N con `tsvector` usando la pregunta original.
6. Se fusionan resultados con RRF, Reciprocal Rank Fusion.
7. Los top-K chunks van como contexto al LLM, que genera la respuesta final.

Pseudoflujo:

```text
question
  -> hyde_answer = LLM(question)
  -> query_embedding = embed(hyde_answer)
  -> vector_results = vector_search(query_embedding, top_n)
  -> lexical_results = lexical_search(question, top_n)
  -> fused_results = rrf(vector_results, lexical_results)
  -> optional_rerank(question, fused_results)
  -> top_k_context
  -> final_answer
```

## Flags de configuracion

Flags sugeridas:

```text
RAG_HYBRID_SEARCH_ENABLED=true
RAG_HYDE_ENABLED=true
RAG_HYDE_SENTENCES=3
RAG_VECTOR_TOP_N=30
RAG_LEXICAL_TOP_N=30
RAG_RRF_K=60
RAG_CONTEXT_TOP_K=8
RAG_RERANK_ENABLED=false
RAG_RERANK_PROVIDER=local_bge
RAG_MEASURE_RETRIEVAL_PERFORMANCE=true
```

Flags para pruebas A/B:

```text
RAG_EXPERIMENT_NAME=hyde_hybrid_v1
RAG_LOG_RETRIEVAL_RESULTS=true
RAG_LOG_CONTEXT_CHUNKS=true
```

## Medicion de rendimiento

Cuando `RAG_MEASURE_RETRIEVAL_PERFORMANCE=true`, registrar:

```json
{
  "question_id": "uuid",
  "experiment_name": "hyde_hybrid_v1",
  "hyde_enabled": true,
  "rerank_enabled": false,
  "total_retrieval_ms": 120,
  "hyde_ms": 40,
  "embedding_ms": 25,
  "vector_search_ms": 20,
  "lexical_search_ms": 15,
  "rrf_ms": 2,
  "rerank_ms": 0,
  "vector_top_n": 30,
  "lexical_top_n": 30,
  "context_top_k": 8,
  "returned_chunk_ids": ["chunk-1", "chunk-2"],
  "returned_source_urls": ["https://..."]
}
```

Metricas a evaluar despues:

- Latencia total.
- Recall manual en preguntas de prueba.
- Precision de fuentes citadas.
- Cantidad de chunks repetidos por fuente.
- Calidad percibida de respuesta.
- Casos donde HyDE empeora o mejora el contexto.
- Impacto de rerank en calidad vs latencia.

## Rerank

Rerank debe ser opcional y desactivado por defecto al inicio:

```text
RAG_RERANK_ENABLED=false
```

Opciones:

### Local Python

Usar un cross-encoder local, por ejemplo:

```text
BAAI/bge-reranker-v2-m3
```

Ventajas:

- No tiene costo por llamada a una API externa.
- Puede probarse como metodo normal de Python.
- Mantiene datos localmente.

Costos reales:

- CPU/GPU.
- RAM.
- Mayor latencia.
- Peso de modelo y dependencias.


## Orden recomendado de implementacion

1. Crear script de embeddings con BGE-M3.
2. Persistir chunks + embeddings + `tsvector`.
3. Implementar busqueda vectorial simple.
4. Implementar busqueda lexica simple.
5. Implementar fusion RRF.
6. Agregar HyDE con flag.
7. Agregar medicion de rendimiento.
8. Evaluar rerank con flag.

## Opinion tecnica

La combinacion Hybrid Search + HyDE + RRF es una buena direccion para MiUni porque mezcla:

- Semantica: encuentra contenido aunque la pregunta no use las mismas palabras.
- Lexico: recupera tramites, nombres, siglas, fechas y terminos exactos.
- HyDE: ayuda cuando la pregunta del usuario es vaga o conversacional.
- RRF: fusiona rankings sin depender demasiado de normalizar scores distintos.

El riesgo principal es complejidad prematura. Por eso conviene implementarlo por flags y medir. Primero necesitamos que la ingesta HTML/PDF este limpia; sin chunks confiables, la busqueda avanzada solo amplifica ruido.
