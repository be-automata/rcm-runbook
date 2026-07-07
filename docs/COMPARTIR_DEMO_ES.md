# Compartir la demo con el cliente (túnel + os.agno.com)

## Arquitectura de la prueba

```
Cliente (navegador) ──▶ os.agno.com (UI de chat de Agno)
                              │  HTTPS + Bearer <OS_SECURITY_KEY>
                              ▼
        https://<subdominio>.trycloudflare.com   (Cloudflare Tunnel)
                              ▼
        tu Mac: uv run rcm-runbook (127.0.0.1:7777, SQLite local)
```

Los datos (sesiones, entregables) nunca salen de tu máquina; Cloudflare solo
enruta el tráfico cifrado. Toda la API exige `Authorization: Bearer` con la
llave `OS_SECURITY_KEY` del `.env` — sin llave, 401.

## Encender (2 comandos, cada sesión de prueba)

```bash
uv run rcm-runbook                                   # terminal 1
cloudflared tunnel --url http://127.0.0.1:7777       # terminal 2 → imprime la URL pública
```

> La URL `*.trycloudflare.com` **cambia en cada arranque** del túnel. Para una
> URL fija + login por email del cliente, use un túnel con nombre + Cloudflare
> Access (requiere cuenta CF y dominio) o el VPS del runbook.

## Conectar os.agno.com (una vez por URL)

1. Entrar a **os.agno.com** con tu cuenta Agno.
2. **Add new OS** (o el selector de endpoint) →
   - **Endpoint/URL**: la URL `https://….trycloudflare.com` del túnel
   - **Security key**: el valor de `OS_SECURITY_KEY` del `.env`
3. Seleccionar el agente **Facilitador RCM** y abrir el chat.
4. Compartir con el cliente: el enlace de os.agno.com **no basta** — necesitan
   entrar con una cuenta Agno con acceso a ese OS, o compartes pantalla tú.
   Para que el cliente pruebe solo, dale la URL del túnel + la llave y que la
   registre en su propio os.agno.com (30 segundos).

## Descarga de entregables

Los enlaces `/exports/...` que da el agente requieren la llave. Formato listo
para navegador:

```
https://<túnel>.trycloudflare.com/exports/<sesión>/AMEF_<TAG>.xlsx?key=<OS_SECURITY_KEY>
```

## Checklist antes de cada sesión con el cliente

- [ ] Mac con corriente y `caffeinate -dims` si la sesión es larga (evita sleep)
- [ ] `curl -s localhost:7777/health` → 200
- [ ] URL nueva del túnel registrada en os.agno.com
- [ ] `RCM_MODEL_ID`: sonnet por defecto; si 429 (ventana de suscripción), relanzar con `claude-haiku-4-5`
- [ ] Plan B abierto: `data/exports/demo/AMEF_P-03070.xlsx` + `docs/DEMO_GUION_ES.md`

## Recoger feedback

- Cada sesión queda completa en `data/rcm_runbook.db` (mensajes, tool calls,
  métricas) y los logs JSON en la terminal del servidor trazan cada decisión.
- Tras cada sesión del cliente: exportar el entregable de su sesión y revisar
  la hoja AUDITORIA RCM — muestra exactamente dónde dudó o se trabó el equipo.
