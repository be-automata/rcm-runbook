# Compartir la demo con el cliente

La demo **ya no depende de tu Mac**: corre en Cloudflare y sigue disponible con
el portátil apagado. El detalle del despliegue está en
[DESPLIEGUE_CLOUDFLARE_ES.md](DESPLIEGUE_CLOUDFLARE_ES.md).

## Arquitectura

```
Cliente (navegador) ──▶ https://rcm-demo.beautomata.com/demo?key=<OS_SECURITY_KEY>
                              │  HTTPS + Bearer <OS_SECURITY_KEY>
                              ▼
        Worker «rcm-runbook» ──▶ Container (imagen Docker: FastAPI + agno)
                              ▼
        Neon Postgres (sesiones) + api.anthropic.com
```

Las sesiones viven en Neon, no en la Mac: el disco del contenedor es efímero y
se borra cuando Cloudflare lo duerme. Los entregables `.xlsx` no se guardan —
se regeneran desde el estado de la sesión al descargarlos.

La API está **cerrada por defecto**: todo exige
`Authorization: Bearer` (o `?key=`) con la `OS_SECURITY_KEY` del `.env`, salvo
dos rutas públicas a propósito, `/demo` y `/health`.

> Esa compuerta es propia (`require_key` en `app.py`), no de Agno. La llave de
> `AgnoAPISettings` dejaba abiertas 22 rutas GET, entre ellas `/sessions` y
> `/sessions/{id}/runs`: cualquiera con la URL pública podía listar las sesiones
> y leer las transcripciones completas. Si algún día subes la versión de Agno,
> vuelve a correr `uv run pytest tests/unit/test_app.py` — ahí está el candado.

**Excepción conocida: el WebSocket.** `wss://…/workflows/ws` acepta el handshake
sin llave. Es deliberado: os.agno.com se autentica *dentro* del protocolo, ya
conectado, así que exigir la llave en el handshake rompería esa integración.
Agno sí bloquea todo lo demás — verificado contra la URL pública: una acción sin
token responde `auth_required`, un token incorrecto `auth_error`, y solo el
correcto `authenticated`. O sea: se puede abrir el socket, no se puede hacer
nada con él. Queda fijado en `TestWebsocketAuth`. Si algún día quieres cerrar
también el handshake, la vía es Cloudflare Access delante del dominio, no tocar
el middleware.

## Encender: nada que encender

Está en Cloudflare. No hay que dejar la Mac despierta ni con corriente.

```bash
npx wrangler deploy                      # publicar un cambio
npx wrangler tail                        # ver logs en vivo
curl -s -o /dev/null -w '%{http_code}\n' https://rcm-demo.beautomata.com/health
```

> El contenedor **duerme a los 20 minutos** sin tráfico (`sleepAfter` en
> `worker/index.ts`). La primera petición después lo despierta y tarda más de lo
> normal; las siguientes van rápido. Si el cliente reporta que «la primera vez
> tarda», es esto, no un fallo.

El túnel a la Mac y sus agentes launchd **quedaron apagados** al migrar
(`launchctl bootout`), y el CNAME del túnel se borró para que el dominio apunte
al Worker. Para desarrollo local sigue funcionando `uv run rcm-runbook` contra
`localhost:7777` con SQLite.

La URL **no cambia**: `https://rcm-demo.beautomata.com`. El enlace directo para
alguien no técnico (un solo click, sin cuenta Agno) es:

```
https://rcm-demo.beautomata.com/demo?key=<OS_SECURITY_KEY>
```

> **VPN local:** con Mullvad conectado, Cloudflare rechaza sus IP de salida y
> `npx wrangler deploy` muere con `GET /accounts -> 522`. Desconéctala antes de
> desplegar. Navegar el sitio ya publicado sí funciona con la VPN puesta.

## Conectar os.agno.com (una sola vez, ya no por sesión)

1. Entrar a **os.agno.com** con tu cuenta Agno.
2. **Add new OS** (o el selector de endpoint) →
   - **Endpoint/URL**: `https://rcm-demo.beautomata.com`
   - **Security key**: el valor de `OS_SECURITY_KEY` del `.env`
3. Seleccionar el agente **Facilitador RCM** y abrir el chat.
4. Compartir con el cliente: el enlace de os.agno.com **no basta** — necesitan
   entrar con una cuenta Agno con acceso a ese OS, o compartes pantalla tú.
   Para que el cliente pruebe solo, dale el enlace `/demo?key=…`, que no
   requiere cuenta.

## La sesión no se pierde (teléfono → computadora)

El enlace simple `/demo?key=…` basta: la página guarda el id de sesión en el
navegador y lo escribe en la barra de direcciones como `&session=…`. De ahí
salen tres comportamientos:

- **Recargar o volver más tarde** en el mismo dispositivo retoma el análisis y
  repinta la conversación anterior.
- **Cambiar de dispositivo**: que copie la URL de su barra de direcciones (ya
  trae `&session=`) y la abra en la otra pantalla. Continúa donde iba.
- **Empezar de cero**: botón **Nuevo análisis** arriba a la derecha.

Para reactivar una sesión concreta desde la base de datos (por ejemplo, si el
cliente perdió el enlace), arma el enlace a mano:

```
https://rcm-demo.beautomata.com/demo?key=<OS_SECURITY_KEY>&session=<session_id>
```

Los ids salen de Neon:

```sql
select session_id, to_timestamp(created_at)
from ai.agno_sessions order by created_at desc limit 10;
```

## Si el cliente reporta un error

| Lo que ve | Causa | Qué hacer |
|---|---|---|
| «Llave de acceso inválida» | Copió el enlace a mano y cortó la llave | Que le dé clic al enlace, sin copiar |
| «Falta la llave de acceso» | El enlace le llegó sin el `?key=` | Reenviárselo completo |
| Página en blanco | Navegador sin `fetch` (muy viejo) | Chrome o Edge actual |
| Tarda mucho la primera vez | El contenedor estaba dormido | Normal; los siguientes turnos van rápido |
| Error de Cloudflare (5xx) | El contenedor no arranca | `npx wrangler tail` y revisar el arranque |

## Lo que la llave NO separa

Es **una sola llave compartida**. Cierra la puerta a desconocidos, no entre
quienes recibieron el enlace: cualquiera con él puede listar `/sessions` y leer
las transcripciones de los demás. Para una demo con dos o tres interesados de
confianza está bien; antes de repartirla más, hace falta Cloudflare Access
(login por correo, revocable por persona) o una llave por invitado.

Dos consecuencias prácticas:

- La llave viaja en la URL, así que aparece en el historial del navegador del
  cliente y en los logs de Cloudflare. En el servidor va redactada (`key=<oculta>`),
  y `~/Library/Logs/rcm-*.log` están en modo 600. Rota la llave cuando termine
  la ronda de demos.
- Si regeneras `OS_SECURITY_KEY`, que sea **segura para URL** (sin `+`, `/`
  ni `=`): `URLSearchParams` decodifica `+` como espacio y los enlaces fallarían
  con «Llave de acceso inválida», imposible de diagnosticar para un no-técnico.

## Descarga de entregables

Los enlaces `/exports/...` que da el agente requieren la llave. Formato listo
para navegador:

```
https://rcm-demo.beautomata.com/exports/<sesión>/AMEF_<TAG>.xlsx?key=<OS_SECURITY_KEY>
```

## Checklist antes de cada sesión con el cliente

- [ ] Comprobar con **`/demo`**, no solo con `/health`:
      `curl -s -o /dev/null -w '%{http_code}' 'https://rcm-demo.beautomata.com/demo?key=<llave>'` → 200
- [ ] Despertar el contenedor unos minutos antes con una petición, para que el
      cliente no se coma el arranque en frío
- [ ] Crédito disponible en la cuenta de Anthropic (la nube usa
      `ANTHROPIC_API_KEY`, no la suscripción)
- [ ] `RCM_MODEL_ID`: sonnet por defecto; si 429 (ventana de suscripción), relanzar con `claude-haiku-4-5`
- [ ] Plan B abierto: `data/exports/demo/AMEF_P-03070.xlsx` + `docs/DEMO_GUION_ES.md`

## Recoger feedback

- Cada sesión queda completa en Neon (`ai.agno_sessions`: mensajes, tool calls,
  métricas) y `npx wrangler tail` muestra los logs en vivo.
- Tras cada sesión del cliente: exportar el entregable de su sesión y revisar
  la hoja AUDITORIA RCM — muestra exactamente dónde dudó o se trabó el equipo.
