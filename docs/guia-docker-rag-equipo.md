# MiUni: guía para principiantes

Esta guía usa Windows y PowerShell. Reemplaza las rutas por las carpetas donde
clonaste los proyectos. Ejecuta los comandos desde la carpeta indicada. Cada servicio
que permanece ejecutándose necesita su propia terminal.

## 1. Qué necesitas para ejecutarlo localmente

Esta guía prepara backend, frontend y RAG locales. El modelo **BGE-M3** son los
archivos que convierten texto en vectores; el **índice** son los documentos y
embeddings calculados que guarda PostgreSQL. Descargar el modelo no carga el índice.

**Si usas la base Docker, necesitas instalar y abrir Docker Desktop.** El `.yml`
describe el contenedor: no incluye Docker ni los documentos ya procesados.
Si tienes una base PostgreSQL externa preparada con extensiones y migraciones,
no necesitas Docker local para conectarte a ella.

## 2. Qué instalar

Para backend/frontend locales: Git, .NET SDK 10 y Node 22.12 o superior compatible
con el lockfile. Para PostgreSQL local siguiendo esta guía: Docker Desktop con
contenedores Linux y WSL 2. Para RAG local: Python 3.12.

Descargar Docker desde su [guía oficial de Windows](https://docs.docker.com/desktop/setup/install/windows-install/).
Abrir Docker Desktop y esperar a que arranque el motor. Incluye Compose.
Si Windows pide instalar/actualizar WSL, seguir el asistente; `wsl --install`
se ejecuta en PowerShell como administrador y puede requerir reiniciar.

Comprobar las herramientas:

```powershell
docker version
docker compose version
dotnet --list-sdks
node --version
py -3.12 --version
```

Docker debe mostrar Client **y Server**. Un error de conexión significa que el motor
no está accesible todavía. No necesitas instalar PostgreSQL aparte en Windows.

Los dos repositorios deben incluir los cambios de Docker, migraciones y RAG en la
rama que use el equipo. Los archivos locales sin commit no llegan a tus compañeros.

## 3. Crear el archivo de configuración de MiUni

En la raíz de **MiUni**, donde está `docker-compose.yml`:

```powershell
cd C:\Dev\miuni\MiUni
powershell -NoProfile -File .\scripts\dev.ps1 -Action init
```

Este comando crea `.env` desde `.env.example` y genera una contraseña de PostgreSQL
y una clave JWT aleatorias. Si `.env` ya existe, se detiene para conservarlo.
**En una instalación ya configurada no repitas `init`: usa `check`.**

```powershell
powershell -NoProfile -File .\scripts\dev.ps1 -Action check
```

`check` valida el archivo sin mostrar secretos; no prueba la conexión de red.
El `.env` contiene:

| Variable | Uso |
| --- | --- |
| `MIUNI_POSTGRES_HOST` | Host de PostgreSQL para el backend; normalmente `127.0.0.1` |
| `MIUNI_POSTGRES_PORT` | Puerto publicado en la máquina; normalmente `5433` |
| `MIUNI_POSTGRES_DB` | Nombre de la base |
| `MIUNI_POSTGRES_USER` | Usuario de PostgreSQL |
| `MIUNI_POSTGRES_PASSWORD` | Contraseña de ese usuario |
| `JWT_KEY` | Clave con la que el backend firma las sesiones |
| `RAG_BASE_URL` | URL de FastAPI, con `/api/v1/` al final |

No publicar `.env`. `.env.example` solo es la plantilla; no contiene claves reales.
Compose exige las variables de base/usuario/contraseña/puerto y falla si faltan.
El launcher lee `.env` y construye la conexión de .NET sin guardarla en un JSON.
Los valores del entorno del proceso tienen prioridad sobre el archivo.

Usar `CLAVE=valor` o `CLAVE='valor literal'`, una variable por línea. El launcher no
ejecuta expresiones ni expande `${OTRA_VARIABLE}`. Para valores especiales usar comillas
simples. `init` genera claves hexadecimales que no necesitan escapes.

**Si ya existe un volumen con datos, cambiar la contraseña en `.env` no cambia la
contraseña almacenada en PostgreSQL.** Conservar su clave actual o hacer una rotación
coordinada. No borrar el volumen para resolver una diferencia de configuración.

## 4. Arrancar la base de datos local

Desde MiUni, con Docker Desktop abierto:

```powershell
docker compose config --quiet
docker compose up -d --build db
docker compose ps
docker compose logs --tail 40 db
```

`config --quiet` valida sin imprimir las variables resueltas. La primera construcción
descarga la imagen PostgreSQL con pgvector y agrega PostGIS/pgRouting. Esperar `healthy`.
Si aparece inicialmente `pull access denied` para la imagen local y luego `Building`,
Compose está construyendo el Dockerfile del proyecto.

Compose solo levanta PostgreSQL. No levanta automáticamente el backend, frontend ni Python.
Los procesos locales usan el host/puerto del `.env`; `db:5432` sirve para contenedores
de la misma red, no para Python/.NET ejecutados en Windows.

## 5. Aplicar las migraciones

Instalar EF CLI si todavía no lo tienes:

```powershell
dotnet tool install --global dotnet-ef --version 10.0.12
```

Si ya existe, usar `dotnet tool update --global dotnet-ef --version 10.0.12`.
Mantener la versión alineada con el proyecto si el equipo actualiza EF.

Desde MiUni:

```powershell
powershell -NoProfile -File .\scripts\dev.ps1 -Action migrate
```

El launcher carga `.env`, selecciona el ambiente Docker, entra en `MiUni.Api` y ejecuta
las migraciones compilando los cambios. Estas crean `documentofuente`, `rag_chunk`,
la columna `vector(1024)` y los índices. **Crear tablas no carga documentos.**

## 6. Entender cuándo hace falta indexar

Las migraciones crean las tablas, pero no cargan los documentos. Un clon del código
tampoco incluye los datos generados ni la caché de BGE-M3.

Si tu base ya contiene el índice completo, pasa directamente a las pruebas del paso 7.
No vuelvas a generar los embeddings. Si empiezas sin índice, prepara Python y los
JSONL completos antes de ejecutar `scripts/index_embeddings.py`.
Los JSONL se colocan en `rag-miuni/data/processed/chunks/`.

Esta guía no configura ningún servicio compartido ni automatiza la distribución
del índice entre compañeros.

## 7. Preparar y probar Python local

En rag-miuni:

```powershell
cd C:\Dev\python\rag-miuni
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-rag.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Reutilizar el venv si ya existe. Editar el `.env` de **rag-miuni**; es distinto al
de MiUni. Configurar `API_KEY` y `DATABASE_URL` con los valores de tu base:

```dotenv
API_KEY=TU_CLAVE_DE_GOOGLE_GENAI
DATABASE_URL=postgresql://USUARIO:CLAVE@127.0.0.1:5433/miuni_dev
RAG_ENABLED=true
RAG_HYBRID_SEARCH_ENABLED=true
RAG_HYDE_ENABLED=true
RAG_RERANK_ENABLED=false
```

Los nombres en mayúsculas de esa URI son marcadores para sustituir. Las claves
generadas por `init` son hexadecimales; si usas una contraseña con caracteres reservados
de URI, codificar esos caracteres. No copiar una conexión con otra contraseña.

```powershell
.\venv\Scripts\python.exe scripts\index_embeddings.py --check-db
.\venv\Scripts\python.exe scripts\search_rag.py 'titulacion' --mode lexical
.\venv\Scripts\python.exe scripts\search_rag.py 'Como puedo titularme?'
```

El primer comando debe mostrar chunks y embeddings, no solo extensión instalada.
El segundo prueba PostgreSQL sin cargar el modelo. El tercero prueba recuperación
híbrida con BGE-M3, sin generar una respuesta final. Revisar las fuentes devueltas.
No volver a ejecutar el indexador completo si ya tienes un índice válido.

Para probar el chat:

```powershell
.\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Abrir `http://127.0.0.1:8000/docs`, elegir **POST /api/v1/chat**, pulsar **Try it out**,
escribir el siguiente JSON y pulsar **Execute**:

```json
{"question":"¿Para qué sirve la Oficina de la Abogacía General?"}
```

Esperado: HTTP 200, `query` y `answer`. Comprobar que la fuente citada respalde la
respuesta. Para otra prueba usar una pregunta cubierta por tus documentos.
Cambios en `.env` requieren reiniciar FastAPI. La primera consulta carga el modelo;
las siguientes reutilizan la misma instancia. Empezar con un solo worker en CPU.

La explicación completa de flags y pruebas está en `rag-miuni/docs/rag-flags-pruebas.md`.

## 8. Arrancar backend y frontend

Terminal del backend, desde MiUni:

```powershell
cd C:\Dev\miuni\MiUni
powershell -NoProfile -File .\scripts\dev.ps1 -Action api
```

El launcher configura la conexión, JWT y URL RAG desde `.env`; arranca en
`http://localhost:5124` con `--no-launch-profile`. Así los perfiles que fijan
`Development` no sobrescriben el ambiente `Docker`. Swagger del backend solo está
habilitado en Development; su ausencia en Docker no es un error de conexión.

Otra terminal para frontend:

```powershell
cd C:\Dev\miuni\MiUni\MiUni.Web
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm ci
npm run dev
```

Dejar `VITE_API_URL=` vacío para usar el proxy Vite hacia `localhost:5124`. Abrir la
dirección que imprima Vite, iniciar sesión y probar el chat. No apuntar el frontend
directamente a Python: el backend maneja autenticación e historial.
Una base nueva no contiene las cuentas, mapas y demás datos de otra computadora;
su carga pertenece al flujo de datos de MiUni.

## 9. Uso diario y errores comunes

- Abrir Docker Desktop si utilizas la base local. `docker compose up -d db` la inicia.
- Iniciar los servicios necesarios: Python, backend y frontend.
- `docker compose stop db` detiene la base conservando datos. No usar `down -v` como
  solución rutinaria: borra el volumen y el índice.
- Si falta `.env`, ejecutar `init` solo para una instalación nueva. Si ya existe un
  volumen, recuperar su configuración antes de elegir nuevas claves.
- Si `config --quiet` dice que falta una variable, completar `.env`.
- Si el puerto está ocupado, cambiar `MIUNI_POSTGRES_PORT` y las conexiones de ambos repositorios.
- Si EF no conecta, revisar host, puerto y contraseña del volumen; usar el launcher `migrate`.
- Si faltan tablas, aplicar las migraciones; si hay cero chunks, todavía falta cargar el índice.
- Si falta memoria al indexar, bajar `RAG_EMBEDDING_BATCH_SIZE` a `2` o `1`.
- Si el backend devuelve 502, probar FastAPI directamente y revisar su log y la API key.
- No imprimir ni compartir `docker compose config` sin `--quiet`: puede mostrar secretos resueltos.

Referencias oficiales: [variables de Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/),
[configuración .NET](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/configuration/).
