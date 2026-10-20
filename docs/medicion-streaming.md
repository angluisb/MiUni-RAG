# Streaming y medición del chat

## Técnicas configuradas

Configuración local comprobada el 19 de octubre de 2026:

| Etapa | Configuración |
| --- | --- |
| Fragmentación | HTML/PDF, hasta 512 palabras por fragmento y solapamiento de 100 |
| Embeddings | BAAI/bge-m3, vectores densos normalizados de 1024 dimensiones, CPU |
| Recuperación vectorial | pgvector, similitud coseno; índice HNSW disponible |
| Recuperación léxica | PostgreSQL full-text en español, `websearch_to_tsquery` y `ts_rank_cd`, índice GIN; no es BM25 |
| Búsqueda híbrida | Hasta 30 candidatos vectoriales y 30 léxicos |
| Fusión | Reciprocal Rank Fusion, constante `k=60` |
| HyDE | Activo: pasaje hipotético de 3 oraciones para buscar vectores; timeout de 15 s y fallback a la pregunta original |
| Contexto final | Hasta 8 fragmentos; la rama léxica siempre usa la pregunta original |
| Generación | Gemini `gemini-3.1-flash-lite`, con contexto documental e instrucciones de citar fuentes |
| Reranking | Implementado, desactivado |
| Indexado incremental | Reutiliza embeddings compatibles por hash, modelo y versión del pipeline |

La configuración activa HyDE, pero una petición concreta puede caer al fallback.
El log `rag_retrieval` distingue `hyde_used`, `hyde_failed` y los tiempos de cada etapa.
BGE-M3 se utiliza aquí solo para vectores densos; no se utilizan sus salidas sparse
ni multivector. El índice no se vuelve a calcular por pregunta.

## Recorrido de streaming

```text
Chat.jsx → lector fetch/ReadableStream
         → Vite /api/Chat/stream
         → .NET RagClient → Python /api/v1/chat/stream
         → Gemini astream
```

La interfaz anterior llamaba `/api/Chat` y esperaba el JSON completo. Ahora llama
`/api/Chat/stream`, agrega el texto recibido progresivamente y obtiene la sesión de
`X-Session-Id`. El decoder conserva caracteres UTF-8 aunque un carácter llegue partido.
Al terminar, consulta el historial y comprueba que la respuesta completa se haya guardado.
Una interrupción no se presenta como una respuesta guardada correctamente.

También se corrigió el backend: asigna `text/plain` cuando envía el primer fragmento.
Así un fallo previo puede devolver JSON con 502, en lugar de fallar la negociación
de contenido y terminar en 406. Un stream vacío también devuelve 502.

## Qué mide cada tiempo

- **Primer texto:** desde enviar la petición hasta recibir el primer texto del asistente.
  Incluye autenticación, HyDE, recuperación, carga de BGE-M3 si hace falta y comienzo de Gemini.
- **Total:** desde enviar la petición hasta finalizar el stream HTTP. No incluye
  la comprobación posterior del historial ni mide el instante exacto de pintado del navegador.
- **Fragmentos recibidos:** partes de texto observadas por el cliente HTTP. No son tokens
  del modelo; servidores y red pueden agruparlas.
- **`total_retrieval_ms` del servidor:** solo recuperación, incluyendo HyDE si se usa;
  no incluye la respuesta final de Gemini.

Una primera medición solo es “en frío” si se sabe que BGE-M3 no estaba cargado.
Repetir preguntas sin reiniciar permite observar consultas con el proceso ya activo.
No cambiar flags ni editar Python durante la medición si FastAPI usa recarga automática.
Tres peticiones secuenciales no permiten estimar capacidad concurrente ni un p95 fiable.

## Resultados reales de esta sesión

Medidos por `http://127.0.0.1:5173/api/Chat/stream`, incluyendo proxy de Vite,
autenticación y backend .NET, recuperación Python y generación. Pregunta repetida:
“¿Para qué sirve la Oficina de la Abogacía General?”

| Petición | Primer texto | Respuesta completa | Partes recibidas | Guardada completa |
| --- | ---: | ---: | ---: | --- |
| Primera de la serie | 98.31 s | 98.48 s | 3 | Sí |
| Segunda, mismo proceso | 4.49 s | 4.88 s | 6 | Sí |
| Tercera, mismo proceso | 3.75 s | 3.78 s | 3 | Sí |

La primera petición fue mucho más lenta. FastAPI ya estaba ejecutándose con recarga
automática; esta medición no separa carga de modelo, HyDE y proveedor de generación.
No atribuir los 98 s completos a una sola etapa ni tratarlos como latencia habitual.
Consultar `rag_retrieval` en la terminal de Python para separar sus tiempos.

Una cuarta petición usó **el mismo módulo `chatStream.js` que importa la interfaz**,
ejecutado con Node y servicios reales. Con una pregunta equivalente pero más breve,
registró primer texto a los **9.78 s**, final a los **10.09 s** y **6 actualizaciones**
del callback de texto; el historial coincidió con la respuesta recibida.
Esta comprobación verifica el lector y el flujo HTTP, no mide el pintado del navegador.

Evidencia local, ignorada por Git:

- `.cache/miuni-stream-benchmark.json`: las tres mediciones finales.
- `.cache/miuni-frontend-stream.json`: medición con el lector del frontend.
- `.cache/miuni-stream-before-fix.json`: serie preliminar, con un error 406 antes
  de corregir el tipo de contenido del backend. No se mezcló con la serie final.

Validación de código: 4 pruebas del lector JavaScript aprobadas, ESLint de los
archivos modificados y build Vite correctos; 25 pruebas .NET aprobadas y 6 pruebas
de integración omitidas por requerir configuración adicional. Se conserva la
advertencia preexistente NU1903 de Microsoft.OpenApi.

## Repetir la medición

Con FastAPI iniciado, desde este repo:

```powershell
.\venv\Scripts\python.exe scripts\benchmark_chat.py --runs 3
```

Esto mide Python directamente, sin frontend ni autenticación .NET. Para incluir
el proxy de Vite y el backend, definir `MIUNI_BENCHMARK_TOKEN` con el JWT de una cuenta
de prueba local y ejecutar:

```powershell
.\venv\Scripts\python.exe scripts\benchmark_chat.py --protocol miuni --url http://127.0.0.1:5173/api/Chat/stream --runs 3 --output .cache/miuni-stream-benchmark.json
```

El token se lee del entorno y no se incluye en el informe. Esta modalidad crea
conversaciones de prueba en la cuenta autenticada y verifica su persistencia.
No compartir tokens ni escribirlos en comandos que se vayan a publicar.

| Opción | Uso |
| --- | --- |
| `--question "texto"` | Misma pregunta para todas las repeticiones |
| `--runs 3` | Entre 1 y 20 peticiones secuenciales |
| `--timeout 180` | Timeout HTTP en segundos; no modifica el timeout del backend |
| `--protocol rag` | Contrato Python: `question`; default |
| `--protocol miuni` | Contrato .NET: `mensaje`, sesión nueva y comprobación del historial |
| `--url URL` | Endpoint completo de streaming |
| `--token-env NOMBRE` | Variable con el JWT; default `MIUNI_BENCHMARK_TOKEN` |
| `--output RUTA` | Informe JSON; default `.cache/chat-benchmark.json`, se reemplaza al medir |

La consola del navegador, en desarrollo, registra `miuni_chat_stream` con
`firstTextMs`, `totalMs`, `textChunks` y `characters` después de cada respuesta.
La pestaña Network debe mostrar **POST `/api/Chat/stream`**. Las consultas GET de
sesiones que aparecen después actualizan el historial.
