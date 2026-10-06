# Contrato de Scraping Web e Ingest HTML para RAG

## Proposito

Este documento define el contrato tecnico para descubrir, descargar, limpiar y trocear contenido publico oficial de la Universidad de Sonora que sera usado por el RAG de MiUni.

El objetivo es producir fuentes y chunks auditables para que el chatbot pueda responder preguntas institucionales con citas a documentos, enlaces o fragmentos utilizados.

Este contrato cubre:

- Paginas HTML oficiales.
- PDFs oficiales descubiertos desde esas paginas.
- Metadata minima para conectar las fuentes con el futuro flujo de embeddings.

Este contrato no cubre:

- Generacion de embeddings.
- Vector DB o pgvector.
- Parsing profundo de PDFs.
- Scraping de sitios con login.
- Scraping de fuentes no oficiales.
- Scraping de datos personales sensibles.

## Relacion con MiUni

El RAG de MiUni debe apoyar principalmente:

- Respuestas sobre tramites, calendarios, reglamentos e informacion institucional.
- Respuestas con transparencia, indicando fuente consultada.
- Actualizacion periodica de fuentes oficiales.
- Reduccion de alucinaciones: si la informacion no esta en las fuentes procesadas, el chatbot debe reconocer que no cuenta con ella.

El contenido obtenido por este pipeline debe poder mapearse despues a entidades del backend como:

- `DocumentoFuente`: catalogo de documentos o URLs procesadas.
- Chunks para embeddings: fragmentos de texto asociados a una fuente.
- `HistorialChat.contexto_utilizado`: referencias a documentos/chunks usados para responder.

## Principios

- Solo se deben usar fuentes oficiales de la Universidad de Sonora.
- Cada fuente debe conservar URL original.
- Cada chunk debe conservar metadata suficiente para auditoria.
- HTML y PDF se tratan como fuentes distintas.
- El scraper debe ser reproducible y tener limites claros.
- El scraper debe respetar politicas del sitio, terminos de uso y buenas practicas de crawling.
- El contenido descubierto debe poder reprocesarse sin trabajo manual complejo.

## Fuentes permitidas

### Dominios de prioridad alta

- `serviciosescolares.unison.mx`
- `www.unison.mx`
- `unison.mx`
- `admision.unison.mx`
- `movilidad.unison.mx`
- `ofertaeducativa.unison.mx`

### Dominios de prioridad media

- `planeacion.unison.mx`
- Subdominios departamentales oficiales `*.unison.mx`, siempre que sean descubiertos desde una pagina oficial confiable, como `www.unison.mx/directorio/`.

### Fuentes excluidas por defecto

- Redes sociales.
- Wikipedia.
- Google Drive externo.
- Sitios de terceros.
- Portales que requieren autenticacion.
- Buscadores internos.
- Sitios de calificacion de profesores, salvo que exista revision explicita de terminos de uso y alcance legal.
- Archivos que no sean HTML o PDF.

## Semillas iniciales

Las semillas deben mantenerse en:

```text
data/sources/web_seed_urls.json
```

### Servicios escolares y tramites

- `https://serviciosescolares.unison.mx/`
- `https://serviciosescolares.unison.mx/directorio/`
- `https://serviciosescolares.unison.mx/requisitos-de-titulacion/`
- `https://serviciosescolares.unison.mx/procedimiento-de-titulacion/`
- `https://serviciosescolares.unison.mx/tabla-de-costos/`

### Normatividad

- `https://www.unison.mx/marco-normativo/`

### Admision y oferta educativa

- `https://admision.unison.mx/convocatoria.php`
- `https://admision.unison.mx/lugares_ofertados.php`
- `https://ofertaeducativa.unison.mx/`

### Movilidad e intercambios

- `https://movilidad.unison.mx/`
- `https://movilidad.unison.mx/internacional-2/`
- `https://movilidad.unison.mx/international-incoming-students/`
- `https://movilidad.unison.mx/normatividad/`

### Directorios y departamentos

- `https://www.unison.mx/directorio/`

El directorio institucional puede usarse para descubrir subdominios oficiales de facultades, jefaturas y departamentos academicos.

## Reglas de crawling

- Profundidad maxima inicial: 2.
- Maximo inicial de paginas HTML: 50.
- Delay entre requests: 0.5 a 1 segundo.
- Solo seguir links de dominios permitidos.
- Normalizar URLs antes de guardarlas.
- Quitar fragmentos `#...`.
- Evitar duplicados.
- Separar URLs HTML y URLs PDF.
- Registrar `source_url`.
- Registrar `discovered_from`.
- Registrar `depth`.
- Registrar `status`.
- Registrar `content_type`.
- Registrar `last_seen_at`.
- No ejecutar JavaScript del sitio en esta fase.
- No enviar formularios.

## Reglas para HTML

El HTML crudo debe guardarse para reproducibilidad.

Ubicacion:

```text
data/raw/html/
```

Tambien debe guardarse metadata por pagina:

```text
data/raw/html/metadata.json
```

Durante ingest HTML se deben eliminar elementos que normalmente contaminan chunks:

- `script`
- `style`
- navegacion repetida
- footer repetido
- menus globales
- widgets laterales irrelevantes
- formularios no necesarios

Se deben conservar, cuando sea posible:

- titulo de pagina
- encabezados `h1`, `h2`, `h3`
- tablas con informacion institucional
- listas de requisitos
- telefonos y correos institucionales si aparecen como contacto publico oficial
- enlaces a PDFs oficiales

## Reglas para PDFs descubiertos

El scraper puede descubrir PDFs desde cualquier pagina permitida.

Debe registrar los PDFs en:

```text
data/sources/discovered_pdfs.json
```

Opcionalmente puede descargarlos a:

```text
data/raw/pdfs/
```

El procesamiento profundo del PDF pertenece al pipeline de ingest PDF, no al ingest HTML.

## Estructura esperada

```text
data/
  raw/
    html/
    pdfs/
  processed/
    chunks/
  sources/
    web_seed_urls.json
    discovered_pages.json
    discovered_pdfs.json
scripts/
  scrape_web.py
  ingest_html.py
  inspect_chunks.py
docs/
  rag-web-scraping.md
```

## Formato de `web_seed_urls.json`

```json
[
  {
    "url": "https://serviciosescolares.unison.mx/",
    "category": "servicios_escolares",
    "priority": "high"
  }
]
```

## Formato de `discovered_pages.json`

```json
[
  {
    "url": "https://serviciosescolares.unison.mx/requisitos-de-titulacion/",
    "title": "Requisitos de Titulacion",
    "status": 200,
    "content_type": "text/html",
    "discovered_from": "https://serviciosescolares.unison.mx/",
    "depth": 1,
    "category": "tramites",
    "last_seen_at": "2026-09-29"
  }
]
```

## Formato de `discovered_pdfs.json`

```json
[
  {
    "url": "https://www.unison.mx/institucional/marconormativo/reglamentosescolares/Reglamento_Escolar_Mayo_2022.pdf",
    "filename": "Reglamento_Escolar_Mayo_2022.pdf",
    "status": 200,
    "content_type": "application/pdf",
    "discovered_from": "https://www.unison.mx/marco-normativo/",
    "depth": 1,
    "category": "normatividad",
    "last_seen_at": "2026-09-29"
  }
]
```

## Formato de `html_chunks.jsonl`

Cada linea debe ser un JSON independiente:

```json
{
  "id": "serviciosescolares-unison-mx-requisitos-de-titulacion-0001",
  "source_type": "html",
  "source_url": "https://serviciosescolares.unison.mx/requisitos-de-titulacion/",
  "document_title": "Requisitos de Titulacion",
  "category": "tramites",
  "chunk_index": 0,
  "content": "Texto limpio del contenido principal...",
  "metadata": {
    "institution": "Universidad de Sonora",
    "domain": "serviciosescolares.unison.mx",
    "section": "Servicios Escolares",
    "last_seen_at": "2026-09-29",
    "raw_html_path": "data/raw/html/serviciosescolares-unison-mx-....html",
    "content_word_count": 312,
    "content_sha256": "hash-del-contenido",
    "chunking_strategy": "paragraph_sliding_window",
    "chunk_max_words": 512,
    "chunk_overlap_words": 100,
    "chunk_min_words": 175
  }
}
```

## Parametros de chunking HTML

El chunking HTML debe usar ventana deslizante con corte por parrafos cuando sea posible:

```text
max_words = 512
min_chunk_words = 175
overlap_words = 100
overlap_percent_aprox = 19.5%
```

Reglas:

- `512` palabras es el maximo por chunk.
- `175` palabras es el minimo deseado.
- El overlap debe mantenerse entre 10% y 25%.
- Se debe cortar por parrafos cuando sea posible.
- Si un parrafo excede `512` palabras, se corta por palabras con sliding window.
- El ultimo chunk puede quedar por debajo del minimo si es necesario para no perder contenido.
- El overlap solo aplica entre chunks consecutivos de la misma fuente.
- No se debe mezclar contenido de paginas distintas.

## Relacion esperada con `DocumentoFuente`

Cada pagina HTML o PDF descubierto debe poder convertirse en un registro conceptual de fuente:

```json
{
  "titulo": "Requisitos de Titulacion",
  "tipo_origen": "URL",
  "referencia": "https://serviciosescolares.unison.mx/requisitos-de-titulacion/",
  "ultima_actualizacion": "2026-09-29"
}
```

Para PDFs:

```json
{
  "titulo": "Reglamento Escolar",
  "tipo_origen": "PDF",
  "referencia": "https://www.unison.mx/.../Reglamento_Escolar_Mayo_2022.pdf",
  "ultima_actualizacion": "2026-09-29"
}
```

## Criterios de calidad de chunks

Un chunk es aceptable si:

- Tiene URL fuente.
- Tiene titulo de documento o pagina.
- Tiene categoria.
- Tiene indice de chunk.
- No contiene HTML bruto.
- No contiene menus repetidos como contenido principal.
- No contiene footer repetido como contenido principal.
- El texto se entiende sin abrir la pagina.
- No mezcla contenido de paginas distintas.
- Tiene longitud razonable para embeddings: maximo `512` palabras, minimo deseado `175` palabras.
- Conserva metadata de estrategia de chunking, conteo de palabras y hash del contenido.

## Criterios de cobertura minima

El corpus HTML inicial debe incluir, como minimo:

- Servicios escolares.
- Tramites o requisitos.
- Admision u oferta educativa.
- Movilidad o intercambios.
- Normatividad.
- Directorio institucional o paginas de departamentos descubiertas desde el directorio.

## Salidas obligatorias

```text
data/sources/discovered_pages.json
data/sources/discovered_pdfs.json
data/raw/html/metadata.json
data/processed/chunks/html_chunks.jsonl
```

## Comandos esperados

```powershell
python scripts/scrape_web.py
python scripts/ingest_html.py
python scripts/inspect_chunks.py
```

## Definition of done

- `web_seed_urls.json` existe y contiene las semillas iniciales.
- `discovered_pages.json` contiene paginas oficiales validas.
- `discovered_pdfs.json` contiene PDFs oficiales descubiertos.
- HTML crudo fue guardado en `data/raw/html/`.
- `html_chunks.jsonl` fue generado.
- Los chunks conservan URL fuente, titulo, categoria y metadata.
- Se reviso manualmente una muestra de chunks.
- El resultado puede usarse como entrada para embeddings en sprint 9.
