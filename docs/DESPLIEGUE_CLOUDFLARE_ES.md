# Despliegue en Cloudflare (Worker + Container)

La demo dejó de vivir en la Mac. Corre en Cloudflare, así que sigue disponible
con el portátil apagado.

## Arquitectura

```
Cliente ──▶ Worker «rcm-runbook»          (enruta, no ejecuta la app)
                    │
                    ▼
            Container: imagen Docker con la app FastAPI + agno
                    │
                    ▼
            Neon Postgres  (sesiones — sobreviven al reinicio)
                    │
                    ▼
            api.anthropic.com  (ANTHROPIC_API_KEY)
```

Dos decisiones que conviene entender antes de tocar nada:

**Por qué Container y no un Worker en Python.** Los Python Workers corren sobre
Pyodide y soportan paquetes puros o compilados a wasm. Este sistema usa `agno`,
`psycopg` y `jiter` (nativo), escribe archivos y abre SQLite: portarlo sería
reescribir la persistencia y los entregables, sin garantía de que las
dependencias compilen. El contenedor corre la misma imagen que se prueba en
local, así que no hay dos implementaciones que mantener sincronizadas.

**Por qué Postgres y no SQLite.** El disco del contenedor es **efímero**:
Cloudflare lo borra cuando el contenedor duerme (`sleepAfter`). Con SQLite el
cliente perdería su análisis entre una visita y la siguiente — justo la
continuidad de sesión que la demo promete. Cloudflare no ofrece Postgres propio
(Hyperdrive solo acelera uno externo), de ahí Neon.

Los entregables `.xlsx` **no se guardan**: `/exports/...` los regenera desde el
estado de la sesión en Postgres. Son función pura de ese estado, así que un
disco borrado no pierde nada.

## Desplegar

```bash
npx wrangler deploy          # construye la imagen, la sube y publica el Worker
```

### Secretos (una sola vez, y al rotarlos)

```bash
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put OS_SECURITY_KEY
npx wrangler secret put DATABASE_URL      # el connection string de Neon
```

`DATABASE_URL` debe llevar el driver de SQLAlchemy:
`postgresql+psycopg://usuario:clave@host/base?sslmode=require`.
Neon entrega `postgresql://...`; hay que insertarle `+psycopg`.

> **Con VPN no se despliega.** Cloudflare rechaza las IP de salida de Mullvad:
> `wrangler deploy` muere con `GET /accounts -> 522` y `curl` a
> `api.cloudflare.com` devuelve 000/521. `mullvad disconnect` antes de desplegar.

## Probar la imagen en local (idéntica a la que se despliega)

```bash
docker build -t rcm-runbook:local .
docker run --rm -p 8080:8080 \
  -e ANTHROPIC_API_KEY=... -e OS_SECURITY_KEY=... \
  -e DATABASE_URL='postgresql+psycopg://...' \
  rcm-runbook:local
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/health
```

El primer arranque contra una base vacía tarda ~60-90 s: Neon despierta su
compute y agno crea las 13 tablas del esquema `ai`. Los siguientes son rápidos.

## Verificar que quedó bien

```bash
BASE=https://<worker>.workers.dev        # o el dominio propio
KEY=<OS_SECURITY_KEY>
curl -s -o /dev/null -w 'health %{http_code}\n' $BASE/health
curl -s -o /dev/null -w 'demo   %{http_code}\n' "$BASE/demo?key=$KEY"
curl -s -o /dev/null -w 'cerrado %{http_code}\n' $BASE/sessions       # debe ser 401
```

La prueba que de verdad importa —que el análisis sobreviva— es conversar,
esperar a que el contenedor duerma y volver: el historial debe repintarse.

## Costos

| Pieza | Plan |
|---|---|
| Worker | incluido |
| Container | requiere Workers de pago (~5 USD/mes) y se cobra por tiempo activo |
| Neon | free tier suficiente para la demo |
| Anthropic | por token consumido, con `ANTHROPIC_API_KEY` |

Ojo con `sleepAfter = "20m"` en `worker/index.ts`: cuanto más alto, menos
arranques en frío para el cliente y más minutos facturados.

## Lo que queda en la Mac

Nada obligatorio. Los agentes launchd (`com.beautomata.rcm-runbook` y
`com.beautomata.rcm-tunnel`) y el túnel siguen sirviendo `rcm-demo.beautomata.com`
para desarrollo. Cuando el despliegue en Cloudflare sea el oficial, conviene
apagarlos para no tener dos sistemas vivos con la misma llave:

```bash
launchctl bootout gui/$(id -u)/com.beautomata.rcm-runbook
launchctl bootout gui/$(id -u)/com.beautomata.rcm-tunnel
```
