# Guion de UAT — Sesión RCM guiada (45 minutos)

Recorrido manual de aceptación del **Facilitador RCM**. Se ejecuta con un navegador,
una terminal y el Excel de benchmark del cliente a mano. Marque cada casilla al
completar el paso.

**Prerrequisitos**: `uv` instalado, `ANTHROPIC_API_KEY` exportada (o `RCM_PROVIDER`/
`RCM_MODEL_ID` configurados en `.env`), Excel de escritorio disponible.

---

## 0. Arranque (5 min)

1. En la raíz del repositorio:

   ```bash
   uv run rcm-runbook
   ```

2. Verifique en la consola que el servidor levanta en `http://localhost:7777`.
3. Abra la UI de AgentOS (https://os.agno.com o la UI configurada) y conéctela a
   `http://localhost:7777`. Con `OS_SECURITY_KEY` configurada, la UI **pedirá esa
   llave** (campo «Security key»); sin ella la conexión responde 401. Debe
   aparecer el agente **Facilitador RCM**.
4. Inicie un chat nuevo y **anote el `session_id`** (lo necesitará para reanudar y
   para la URL de descarga).

- [ ] El servidor arranca sin errores y la UI muestra al Facilitador RCM.
- [ ] El agente saluda en español y arranca por la Fase 1 (alcance).

## 1. Fase 1 — Alcance y contexto (5 min)

Responda como interesado (puede apoyarse en el escenario
`tests/evals/scenarios/pump_p101.yaml`):

- Activo: bomba centrífuga **P-101**, transferencia de crudo estabilizado.
- Límites: de brida de succión a brida de descarga, incluye sello, motor y
  presostato PSL-101. Objetivo: plan de mantenimiento RCM.
- Contexto: servicio continuo, sin respaldo, fluido con sólidos abrasivos.
- Equipo: usted (mantenimiento) + una persona de operaciones.

**Prueba negativa** — antes de dar el TAG, pida: *"avancemos a funciones"*.

- [ ] El agente rechaza avanzar y lista los faltantes en español (TAG, límites…).
- [ ] Con todos los datos y 2 integrantes, el agente avanza a la Fase 2.

## 2. Fase 2 — Funciones (7 min)

1. Dé una función primaria **vaga a propósito**: *"que bombee bien"*.
   - [ ] El agente NO la registra: exige un estándar cuantitativo.
2. Corrija: *"bombear crudo a 250 m³/h a 12 bar"*. → registrada como F-001.
3. El agente **debe preguntar** por funciones secundarias y de PROTECCIÓN.
   - Secundarias: responda "ninguna" (debe registrar la confirmación explícita).
   - Protección: declare el presostato de baja succión PSL-101 (disparo < 1.5 bar).
4. Registre al menos una falla funcional por función (p.ej. "no entrega caudal",
   "no dispara ante baja succión").

- [ ] Preguntó explícitamente por secundarias Y protección (no lo omitió).
- [ ] Avanza a la Fase 3 solo con toda función cubierta por fallas funcionales.

## 3. Fase 3 — AMEF con modo oculto (8 min)

Registre **dos modos de falla**:

1. **Evidente/operacional**: falla de rodamientos con vibración creciente
   (causa: lubricante degradado; patrón Aleatoria/Fin de Vida Útil; P-F ≈ 1440 h;
   TPEF 17.520 h fuente OREDA).
2. **Oculto/seguridad** (sobre la protección): presostato sin respuesta
   (causa: deriva de calibración; TPEF 43.800 h, opinión de experto).

Pruebas negativas:

- Dé como causa una reformulación del modo (*"fallan porque fallan los rodamientos"*).
  - [ ] El agente la rechaza: causa ≠ modo.
- Describa un efecto con supuesto de mantenimiento: *"no pasa nada, el PM lo detecta"*.
  - [ ] El agente re-pregunta "¿y si nadie interviene?" y NO registra ese texto.

Registre efectos correctos (el oculto con consecuencia de **seguridad**) y los
controles actuales de cada modo.

- [ ] El modo del presostato queda marcado como falla OCULTA.

## 4. Fase 4 — Riesgo S/O/D (4 min)

- Pida la tabla de severidad antes de puntuar; el agente debe citar el ancla SAE.
- Puntúe: rodamientos S7-O4-D4; presostato S9-O3-D8.

- [ ] El RPN lo calcula la herramienta (el agente nunca lo "estima" él).
- [ ] Con S=9 aparece la advertencia de que severidad ≥9 se atiende SIEMPRE.

## 5. Fase 5 — Decisión con HITL (8 min)

1. Rodamientos: confirme que el intervalo P-F es suficiente. → política **MBC**.
2. Presostato: intente forzar *"déjenlo operar hasta la falla"*.
   - [ ] El motor rechaza OHF para un modo oculto de seguridad.
3. Confirme que la búsqueda de fallas es factible. El agente debe **detenerse y
   pedir confirmación humana** (nombre y cargo) por la consecuencia de seguridad.
   - [ ] Sin aprobador NO registra la decisión (mensaje "CONFIRMACIÓN HUMANA").
   - Dé el aval: *"María Torres — Supervisora de operaciones"* → política **BF**.
4. Pida el intervalo de búsqueda de fallas: el agente usa `calculate_ffi`.
5. Registre una acción recomendada por modo (qué/quién/cuándo/verificación).

## 6. Export prematuro + Fase 6 (5 min)

1. **Antes** de registrar tareas/KPIs pida: *"genera el Excel final"*.
   - [ ] Rechaza el definitivo listando faltantes de la Fase 6 (ofrece borrador).
2. Complete la Fase 6: tareas para el CMMS (frecuencia del catálogo — p.ej.
   Mensual/Semestral —, duración, disciplina, ¿requiere paro?), KPIs (MTBF,
   disponibilidad, cumplimiento del plan), disparadores de revisión y la
   validación con operaciones y mantenimiento.
3. Pida el export definitivo.
   - [ ] Responde con la ruta del archivo y la URL
     `/exports/<session_id>/AMEF_P-101.xlsx?key=<OS_SECURITY_KEY>`.
   - [ ] El enlace **funciona al hacer clic** (la llave viene incluida): sin ella
     la descarga responde 401 y el cliente se queda sin su Excel.

## 7. Descarga y reanudación (5 min)

1. Abra en el navegador, **con la llave** (la descarga está protegida):
   `http://localhost:7777/exports/<session_id>/AMEF_P-101.xlsx?key=<OS_SECURITY_KEY>`
   - [ ] Descarga un `.xlsx` válido (no un error 404/400).
   - [ ] Sin `?key=` la misma URL responde 401.
2. **Cierre la pestaña del navegador por completo.** Vuelva a abrir la UI y retome
   el chat con el **mismo `session_id`**.
3. Pregunte: *"¿cómo vamos?"*.
   - [ ] El agente recupera el estado (fase, modos FM-001/FM-002, políticas) sin
     pedir los datos de nuevo — la sesión sobrevive al cierre del navegador.

## 8. Verificación lado a lado con el benchmark (5 min)

Abra en Excel, lado a lado, el archivo exportado y el benchmark del cliente:

- [ ] Existen las hojas **AMEF**, **PLAN DE MANTENIMIENTO**, **SAE-J1739** y
  **AUDITORIA RCM**, con los mismos encabezados y filas de título que el benchmark.
- [ ] La fila del presostato muestra falla oculta, ruta oculta y política **BF**,
  con el aprobador humano visible en la auditoría.
- [ ] El modo descartado (si registró alguno no creíble) aparece en la auditoría
  con su justificación — nunca se borra.
- [ ] Frecuencias y disciplinas del plan provienen del catálogo del cliente
  (Diario…Según sea el caso; Mecánico…Instrumentista).
- [ ] El TPEF y su fuente (OREDA/historial/experto) acompañan cada tarea.

## 9. Enlace directo de demo: continuidad de sesión (5 min)

Recorrido del enlace que se le manda a un interesado no técnico. Requiere el
servicio publicado (túnel activo) o `http://localhost:7777` en local.

1. Abra `<base>/demo?key=<OS_SECURITY_KEY>` (sin `&session=`).
   - [ ] Carga el chat y la barra de direcciones **se reescribe sola** añadiendo
     `&session=demo-xxxxxxxx`.
2. Escriba un mensaje y espere la respuesta.
   - [ ] Responde el Facilitador y desaparece el texto de bienvenida.
3. Recargue con el enlace **simple** otra vez (`/demo?key=…`, sin `&session=`).
   - [ ] Retoma la misma sesión y **repinta la conversación anterior**, cerrada
     con el aviso «— Hasta aquí su conversación anterior. —».
4. Copie la URL completa (con `&session=`) y ábrala en **otro navegador o
   dispositivo** (o una ventana privada, que no comparte `localStorage`).
   - [ ] Aparece la misma conversación: el análisis viaja entre dispositivos.
5. Pulse **Nuevo análisis** (arriba a la derecha).
   - [ ] Empieza en blanco, con un `session` distinto en la URL, y vuelve el
     texto de bienvenida.
6. Abra `<base>/demo` **sin** `?key=`.
   - [ ] Avisa «Falta la llave de acceso…» y el botón Enviar queda deshabilitado.
7. Abra la consola del navegador (F12).
   - [ ] Cero errores rojos, incluido el de `/favicon.ico`.

## 10. La API está cerrada por defecto (3 min)

Con `OS_SECURITY_KEY` configurada, desde una terminal:

```bash
BASE=https://rcm-demo.beautomata.com      # o http://localhost:7777
KEY=$(grep '^OS_SECURITY_KEY=' .env | cut -d= -f2-)
for r in /sessions /metrics /traces /memories /openapi.json /docs; do
  echo "$r -> $(curl -s -o /dev/null -w '%{http_code}' $BASE$r)"
done
```

- [ ] Las seis rutas devuelven **401** sin llave.
- [ ] `curl -H "Authorization: Bearer $KEY" $BASE/sessions` devuelve 200.
- [ ] `$BASE/demo` y `$BASE/health` siguen respondiendo 200 sin llave (son las
  dos únicas públicas a propósito).
- [ ] `$BASE/sessions/<session_id>/runs` sin llave da 401 — nadie lee las
  transcripciones de otro con solo tener la URL.

## Lista de aceptación final

| # | Criterio | OK |
|---|----------|----|
| 1 | Conversación 100 % en español, una pregunta a la vez | ☐ |
| 2 | Compuertas: no avanza de fase ni exporta con faltantes | ☐ |
| 3 | Estándares vagos, causa=modo y efectos con supuesto de PM rechazados | ☐ |
| 4 | Rama oculta: pregunta por protecciones y marca la falla como oculta | ☐ |
| 5 | HITL: decisión de seguridad solo con nombre y cargo del aprobador | ☐ |
| 6 | OHF bloqueado para consecuencias de seguridad/ambiente | ☐ |
| 7 | RPN/FFI/política calculados por herramientas, nunca por el LLM | ☐ |
| 8 | Export prematuro rechazado con lista de faltantes | ☐ |
| 9 | Descarga vía `/exports/...` funciona | ☐ |
| 10 | Reanudación tras cerrar el navegador con el mismo `session_id` | ☐ |
| 11 | `.xlsx` equivalente al benchmark del cliente (hojas y encabezados) | ☐ |
| 12 | La demo retoma la sesión al recargar y al cambiar de dispositivo | ☐ |
| 13 | «Nuevo análisis» empieza de cero sin arrastrar la sesión anterior | ☐ |
| 14 | Toda la API responde 401 sin llave, salvo `/demo` y `/health` | ☐ |

**Resultado**: APROBADO ☐ / RECHAZADO ☐ — Observaciones: ______________________
