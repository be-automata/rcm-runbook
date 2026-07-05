# RCM Runbook — Agente Facilitador RCM

Agente de IA (Agno + AgentOS) que guía a los interesados del cliente, **en español**,
para elaborar un análisis de Mantenimiento Centrado en la Fiabilidad (RCM) basado en
FMEA **SAE J1739** con lógica de decisión **SAE JA1011/JA1012**, y produce el
entregable Excel con el formato del benchmark del cliente (hojas **AMEF** y
**PLAN DE MANTENIMIENTO**, más **SAE-J1739** y **AUDITORIA RCM**).

## Arquitectura

- **Un solo agente Agno** (Facilitador RCM) + **herramientas determinísticas**: el LLM
  solo conversa; todo cambio de estado pasa por herramientas tipadas que mutan el
  agregado `RCMSession` (Pydantic). RPN, FFI y la selección de política de
  mantenimiento son Python puro (`src/rcm_runbook/engine/`) — nunca el LLM.
- **Máquina de 6 fases con compuertas**: alcance → funciones → AMEF → riesgo →
  decisión RCM → plan. `advance_phase`/`export_excel` se rechazan con la lista de
  faltantes en español si la fase está incompleta.
- **HITL**: consecuencias de Seguridad/Ambiente exigen confirmación humana explícita
  (nombre y cargo) registrada en el libro de auditoría.
- **Contrato con el dialecto Excel del cliente**: la estructura del benchmark está
  congelada en `src/rcm_runbook/data/benchmark_fixture.json` (generada por
  `scripts/extract_benchmark.py`); los catálogos y los tests dorados consumen el
  mismo fixture, así el modelo y el entregable no pueden divergir.

```
src/rcm_runbook/
├── models/      # catalogs (fixture-driven), domain (entidades+validadores), session (agregado)
├── engine/      # scoring (RPN), decision_logic (cascada JA1011), ffi, compliance (compuertas)
├── export/      # rows (proyecciones), excel (openpyxl, 4 hojas)
├── agent/       # tools (21 herramientas), instructions_es, factory
├── knowledge/   # consult_handbook (lookup por encabezados)
├── observability.py, config.py, app.py (AgentOS + /exports)
└── data/benchmark_fixture.json
```

## Puesta en marcha

```bash
uv sync --all-groups
cp .env.example .env        # y coloque su ANTHROPIC_API_KEY
uv run rcm-runbook          # AgentOS en http://localhost:7777
```

Conecte la UI de AgentOS (control plane de Agno, [os.agno.com](https://os.agno.com))
apuntando a `http://localhost:7777`, o consuma la API directamente
(`POST /agents/{agent_id}/runs`). Salud: `GET /health`.

## Runbook de operación

| Qué | Cómo |
|---|---|
| Variables de entorno | `.env` (prefijo `RCM_`): ver `.env.example` |
| Cambiar de proveedor LLM | `RCM_PROVIDER=anthropic\|openai\|google` + `RCM_MODEL_ID=...` y la API key correspondiente; reiniciar |
| Base de datos | SQLite en `RCM_DB_PATH` (default `data/rcm_runbook.db`); sesiones, historial y métricas de Agno. **Backup**: copiar el archivo con el servicio detenido |
| Entregables | `RCM_EXPORTS_DIR` (default `data/exports/`); descarga vía `GET /exports/{session_id}/{archivo}.xlsx` |
| Re-generar un export fallido | pedir al agente «exporta de nuevo» (o `export_excel draft=True` para borrador) |
| Logs | JSON estructurado en stdout (`RCM_LOG_LEVEL`); cada tool call y cada decisión del motor quedan trazadas (auditoría JA1011) |
| Tracing OTel | `RCM_OTEL_ENABLED=true` + `uv add opentelemetry-sdk opentelemetry-exporter-otlp-proto-http` y `OTEL_EXPORTER_OTLP_ENDPOINT` |
| Reanudar sesión | misma `session_id` — el estado persiste en SQLite entre reinicios; un esquema más nuevo que el binario falla en voz alta (actualizar antes de reanudar) |
| Actualizar el benchmark del cliente | reemplazar `data/reference/amef_benchmark.xls`, correr `uv run python scripts/extract_benchmark.py`, revisar el diff del fixture y correr `uv run pytest` |

Sin Docker en el MVP (decisión explícita); el despliegue es `uv run rcm-runbook`
detrás del proxy que prefiera.

## Verificación

```bash
uv run ruff check && uv run mypy src   # estático
uv run pytest                          # unit + export dorado (sin LLM)
uv run pytest -m eval                  # eval conversacional (requiere API key)
```

- **Tests dorados** (`tests/export/`): estructura del .xlsx contra el fixture
  congelado — encabezados literales, orden de columnas, dropdowns en el archivo
  guardado.
- **Sesión guionada** (`tests/unit/test_tools.py`): recorre las 6 fases por las
  herramientas reales hasta exportar, sin LLM.
- **Eval conversacional** (`tests/evals/`): un segundo agente simula a un ingeniero
  de mantenimiento (con sondas adversarias) y se valida el ESTADO final, no la prosa.
- **UAT manual**: `docs/UAT_SCRIPT_ES.md` (45 min).

## Pendientes de confirmación con el cliente

- Semántica de los códigos de política **ExEd** (Exploración de edad) y **CC**
  (Control de Calidad) dentro del diagrama de decisión — el MENU del benchmark ya
  fija sus etiquetas; las decisiones que los usen se marcan `provisional`.
- Significado exacto de las letras de ruta **ABCD/AEFG** (derivación provisional
  documentada en `engine/decision_logic.py`).

## Documentos

- `docs/client_method_20_steps.md` — método de 20 pasos del cliente, destilado
- `docs/GLOSARIO.md` — lenguaje ubicuo (término ES ↔ código ↔ columna Excel)
- `docs/UAT_SCRIPT_ES.md` — guion de aceptación manual
- `docs/rcm_handbook_com.md` — manual RCM (fuente de `consult_handbook`)
