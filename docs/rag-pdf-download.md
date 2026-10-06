# Contrato de Descarga de PDFs para RAG

## Proposito

Este documento define el contrato inicial para descargar PDFs oficiales descubiertos por el scraper web de MiUni.

La descarga de PDFs debe producir archivos locales auditables, reproducibles y asociados a su URL original. Este paso prepara el material para una fase posterior de extraccion de texto y generacion de chunks.

Este contrato cubre:

- Lectura de PDFs descubiertos en `data/sources/discovered_pdfs.json`.
- Validacion de dominio, tipo de archivo y respuesta HTTP.
- Descarga a `data/raw/pdfs/`.
- Registro de metadata por PDF descargado.
- Filtros iniciales para evitar documentos personales o fuera de alcance.

Este contrato no cubre:

- Extraccion de texto desde PDFs.
- OCR.
- Chunking de PDFs.
- Embeddings.
- Vector DB.

## Relacion con el pipeline web

El scraper HTML ya descubre enlaces a PDFs y los registra en:

```text
data/sources/discovered_pdfs.json
```

Ese archivo es la entrada principal del pipeline de descarga.

Flujo esperado:

```text
scrape_web.py
  -> discovered_pdfs.json
  -> download_pdfs.py
  -> data/raw/pdfs/
  -> data/raw/pdfs/metadata.json
  -> ingest_pdf.py
  -> data/processed/chunks/pdf_chunks.jsonl
```

## Entrada esperada

Cada registro de `discovered_pdfs.json` debe tener, como minimo:

```json
{
  "url": "https://www.unison.mx/.../Reglamento_Escolar_Mayo_2022.pdf",
  "filename": "Reglamento_Escolar_Mayo_2022.pdf",
  "status": null,
  "content_type": "application/pdf",
  "discovered_from": "https://www.unison.mx/marco-normativo/",
  "depth": 1,
  "category": "normatividad",
  "last_seen_at": "2026-10-06"
}
```

## Salidas esperadas

Los PDFs descargados deben guardarse en:

```text
data/raw/pdfs/
```

La metadata de descarga debe guardarse en:

```text
data/raw/pdfs/metadata.json
```

Formato sugerido de metadata:

```json
[
  {
    "url": "https://www.unison.mx/.../Reglamento_Escolar_Mayo_2022.pdf",
    "filename": "www-unison-mx-reglamento-escolar-mayo-2022-a1b2c3d4.pdf",
    "original_filename": "Reglamento_Escolar_Mayo_2022.pdf",
    "raw_pdf_path": "data/raw/pdfs/www-unison-mx-reglamento-escolar-mayo-2022-a1b2c3d4.pdf",
    "status": 200,
    "content_type": "application/pdf",
    "content_length": 123456,
    "sha256": "hash-del-archivo",
    "discovered_from": "https://www.unison.mx/marco-normativo/",
    "category": "normatividad",
    "last_downloaded_at": "2026-10-06",
    "download_status": "downloaded"
  }
]
```

## Reglas de descarga

- Descargar solo URLs oficiales de la Universidad de Sonora.
- Permitir dominios `*.unison.mx` y `*.uson.mx` cuando fueron descubiertos desde una fuente oficial.
- Rechazar redirecciones finales a dominios externos.
- Usar `GET` con timeout definido.
- Respetar un delay entre descargas.
- Validar que el `content-type` final sea PDF o que el contenido inicie con firma `%PDF`.
- Guardar el PDF con nombre seguro y estable.
- Incluir un hash corto o completo para evitar colisiones de nombres.
- Registrar descargas fallidas sin detener todo el proceso.
- Evitar duplicados por URL normalizada.
- Evitar duplicados de contenido por `sha256`.

## Filtros de privacidad y alcance

Por defecto, el downloader debe saltar PDFs que parezcan contener informacion personal o curricular, aunque hayan sido descubiertos desde una pagina oficial.

Patrones iniciales para marcar como `skipped_review_required`:

- `cv`
- `curriculum`
- `curriculum-vitae`
- `vitae`
- `semblanza`

Tambien se deben saltar por defecto documentos administrativos o presupuestales que no son foco del proyecto. Estos quedan como `skipped_out_of_scope`.

Patrones iniciales:

- `contraloria.unison.mx`
- `codigo-de-conducta`
- `codigo-de-etica`
- `presupuest`
- `fondo-revolvente`
- `disposicion-administrativa`
- `responsabilidades-administrativas`
- `reglamentosydisposicionesadministrativas`
- `ley-organica`
- `manual-general-de-organizacion`
- `manual-de-organizacion`
- `mensaje-de-rectora`
- `mo-dach`
- `mo-dir-servicios-escolares`
- `pdi`
- `plan-de-desarrollo`
- `programa-8m`
- `programa-interno-de-proteccion-civil`
- `jubilacion`
- `auditoria-interna`

Para PDFs de categoria `normatividad`, la regla debe ser todavia mas estricta: solo se descargan automaticamente si parecen utiles para estudiantes. Patrones permitidos:

- reglamento escolar
- movilidad
- becas
- cuotas, colegiatura o inscripcion
- servicio social
- practicas profesionales
- titulacion
- certificado de pasante
- convocatorias
- plan de estudios o mapa curricular
- exencion de pagos
- derechos universitarios
- violencia de genero

El resto de normatividad general, como constituciones, estatutos, PDI, modelos educativos, convenios laborales, jubilaciones o reglas administrativas internas, queda fuera del corpus inicial.

Ejemplo:

```json
{
  "url": "https://campushermosillo.unison.mx/.../CV_Dr.-Nombre.pdf",
  "download_status": "skipped_review_required",
  "skip_reason": "possible_personal_document"
}
```

Estos documentos pueden revisarse manualmente despues, pero no deben entrar automaticamente al corpus RAG inicial.

## Manejo de errores

Estados sugeridos:

- `downloaded`: archivo descargado y validado.
- `already_downloaded`: URL o hash ya existe.
- `skipped_review_required`: documento requiere revision humana.
- `skipped_out_of_scope`: documento oficial pero fuera del foco RAG inicial.
- `skipped_external_redirect`: redireccion final fuera de dominios oficiales.
- `skipped_not_pdf`: respuesta no parece PDF.
- `failed_http`: respuesta HTTP no exitosa.
- `failed_timeout`: timeout.
- `failed_request`: error de red u otro error de requests.

## Limites iniciales

Valores sugeridos para la primera implementacion:

```text
timeout_seconds = 30
delay_seconds = 0.5
max_pdfs = 100
max_file_mb = 50
```

El limite `max_pdfs` debe poder configurarse por CLI.

## Comando esperado

```powershell
python scripts\download_pdfs.py --max-pdfs 100 --delay 0.5
```

Opciones esperadas:

```text
--input data/sources/discovered_pdfs.json
--output-dir data/raw/pdfs
--metadata data/raw/pdfs/metadata.json
--max-pdfs 100
--delay 0.5
--timeout 30
--include-review-required
```

La opcion `--include-review-required` solo debe usarse si ya se reviso que esos PDFs son adecuados para el corpus.

## Chunking y overlap

La descarga de PDFs no debe generar chunks. El chunking pertenece a `ingest_pdf.py`.

Referencia actual del chunking:

```text
max_words = 512
overlap_words = 100
min_chunk_words = 175
strategy = paragraph_sliding_window
```

Para PDFs se recomienda usar los mismos valores iniciales:

```text
max_words = 512
overlap_words = 100
min_chunk_words = 175
```

Reglas recomendadas para PDF:

- No mezclar contenido de PDFs distintos.
- Cortar por parrafos cuando sea posible.
- Si un parrafo excede `512` palabras, cortar por sliding window.
- Evitar cruzar paginas cuando el cambio de pagina representa un corte natural.
- Conservar `page_start` y `page_end` en metadata.
- Conservar `source_url`, `raw_pdf_path`, `document_title`, `category` y `sha256`.
- Aplicar overlap solo entre chunks consecutivos del mismo documento.
- No aplicar overlap cuando el documento completo cabe en un solo chunk.

Formato sugerido de `pdf_chunks.jsonl`:

```json
{
  "id": "www-unison-mx-reglamento-escolar-0001",
  "source_type": "pdf",
  "source_url": "https://www.unison.mx/.../Reglamento_Escolar_Mayo_2022.pdf",
  "document_title": "Reglamento Escolar",
  "category": "normatividad",
  "chunk_index": 0,
  "content": "Texto extraido del PDF...",
  "metadata": {
    "institution": "Universidad de Sonora",
    "domain": "www.unison.mx",
    "raw_pdf_path": "data/raw/pdfs/www-unison-mx-reglamento-escolar-a1b2c3d4.pdf",
    "page_start": 1,
    "page_end": 2,
    "sha256": "hash-del-archivo",
    "last_downloaded_at": "2026-10-06"
  }
}
```

## Criterios de aceptacion

- `download_pdfs.py` lee `discovered_pdfs.json`.
- Los PDFs validos quedan en `data/raw/pdfs/`.
- `data/raw/pdfs/metadata.json` registra resultados exitosos, saltados y fallidos.
- No se descargan redirecciones externas.
- No se descargan automaticamente PDFs marcados como posibles documentos personales.
- Cada PDF descargado conserva URL original, categoria, fuente de descubrimiento y hash.
- La salida queda lista para una fase posterior de `ingest_pdf.py`.
