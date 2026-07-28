# Compartir la demo con el cliente (túnel + os.agno.com)

## Arquitectura de la prueba

```
Cliente (navegador) ──▶ https://rcm-demo.beautomata.com/demo?key=<OS_SECURITY_KEY>
                              │  HTTPS + Bearer <OS_SECURITY_KEY>
                              ▼
        Cloudflare Tunnel con nombre «rcm-runbook» (URL fija)
                              ▼
        tu Mac: uv run rcm-runbook (127.0.0.1:7777, SQLite local)
```

Los datos (sesiones, entregables) nunca salen de tu máquina; Cloudflare solo
enruta el tráfico cifrado. La API está **cerrada por defecto**: todo exige
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

## Encender: nada, ya está encendido

Dos agentes de `launchd` mantienen vivos el servidor y el túnel. Arrancan solos al
iniciar sesión en la Mac y `KeepAlive` los resucita si se caen (probado con
`kill -9`: vuelven en ~4 s).

| Servicio | Etiqueta | Log |
|---|---|---|
| App | `com.beautomata.rcm-runbook` | `~/Library/Logs/rcm-runbook.log` |
| Túnel | `com.beautomata.rcm-tunnel` | `~/Library/Logs/rcm-tunnel.log` |

```bash
launchctl print gui/$(id -u)/com.beautomata.rcm-runbook | grep -E "state|pid ="
launchctl kickstart -k gui/$(id -u)/com.beautomata.rcm-runbook   # reiniciar (tras cambiar código)
launchctl kickstart -k gui/$(id -u)/com.beautomata.rcm-tunnel
launchctl bootout gui/$(id -u)/com.beautomata.rcm-runbook        # apagar del todo
```

> **Cuidado con `pkill`:** `pkill -f "run rcm-runbook"` también mata el servidor,
> porque el patrón casa con `uv run rcm-runbook`. Para el túnel solamente:
> `pkill -f "cloudflared.*rcm-runbook"`. Con launchd, mejor usar `kickstart`.

Si prefieres correrlo a mano (sin launchd), son los dos comandos de siempre:

```bash
uv run rcm-runbook
cloudflared tunnel --config ~/.cloudflared/rcm-runbook.yml run rcm-runbook
```

La URL **no cambia**: `https://rcm-demo.beautomata.com`. El enlace directo para
alguien no técnico (un solo click, sin cuenta Agno) es:

```
https://rcm-demo.beautomata.com/demo?key=<OS_SECURITY_KEY>
```

Detalles del túnel con nombre:

- Túnel `rcm-runbook`, id `99d06e9b-a057-46cc-b5b9-0a88c2cf04c5`
- Config e ingress: `~/.cloudflared/rcm-runbook.yml` → `http://127.0.0.1:7777`
- DNS: CNAME `rcm-demo.beautomata.com` → `<id>.cfargotunnel.com` (creado con
  `cloudflared tunnel route dns`)
- Abre 4 conexiones al edge, así que aguanta cortes de red mucho mejor que un
  túnel rápido (`--url`), que solo abre una.

> **VPN local:** con Mullvad conectado, su resolver DNS devuelve NXDOMAIN para
> subdominios de `trycloudflare.com` — por eso los túneles rápidos no abrían
> desde tu propia Mac. `rcm-demo.beautomata.com` sí resuelve con la VPN puesta.

## Conectar os.agno.com (una sola vez, ya no por sesión)

1. Entrar a **os.agno.com** con tu cuenta Agno.
2. **Add new OS** (o el selector de endpoint) →
   - **Endpoint/URL**: `https://rcm-demo.beautomata.com`
   - **Security key**: el valor de `OS_SECURITY_KEY` del `.env`
3. Seleccionar el agente **Facilitador RCM** y abrir el chat.
4. Compartir con el cliente: el enlace de os.agno.com **no basta** — necesitan
   entrar con una cuenta Agno con acceso a ese OS, o compartes pantalla tú.
   Para que el cliente pruebe solo, dale la URL del túnel + la llave y que la
   registre en su propio os.agno.com (30 segundos).

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

Los ids están en `sqlite3 data/rcm_runbook.db "select session_id, datetime(created_at,'unixepoch') from agno_sessions order by created_at desc limit 10"`.

## Si el cliente reporta un error

| Lo que ve | Causa | Qué hacer |
|---|---|---|
| «Llave de acceso inválida» | Copió el enlace a mano y cortó la llave | Que le dé clic al enlace, sin copiar |
| «Falta la llave de acceso» | El enlace le llegó sin el `?key=` | Reenviárselo completo |
| Página en blanco | Navegador sin `fetch` (muy viejo) | Chrome o Edge actual |
| Error de Cloudflare (502/530) | El túnel o la app están caídos | `launchctl print` a los dos servicios y revisar los logs |

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

- [ ] Mac con corriente y `caffeinate -dims` si la sesión es larga (evita sleep)
- [ ] Los dos servicios en `running`:
      `launchctl print gui/$(id -u)/com.beautomata.rcm-runbook | grep state`
- [ ] `curl -s localhost:7777/health` → 200
- [ ] Comprobar con **`/demo`**, no con `/health`: durante un aleteo del túnel se
      ha visto `/health` en 200 con `/demo` todavía en 502.
      `curl -s -o /dev/null -w '%{http_code}' 'https://rcm-demo.beautomata.com/demo?key=<llave>'` → 200
- [ ] `RCM_MODEL_ID`: sonnet por defecto; si 429 (ventana de suscripción), relanzar con `claude-haiku-4-5`
- [ ] Plan B abierto: `data/exports/demo/AMEF_P-03070.xlsx` + `docs/DEMO_GUION_ES.md`

## Recoger feedback

- Cada sesión queda completa en `data/rcm_runbook.db` (mensajes, tool calls,
  métricas) y los logs JSON en la terminal del servidor trazan cada decisión.
- Tras cada sesión del cliente: exportar el entregable de su sesión y revisar
  la hoja AUDITORIA RCM — muestra exactamente dónde dudó o se trabó el equipo.
