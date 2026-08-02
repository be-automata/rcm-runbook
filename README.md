# RCM Runbook

**Un agente que conduce una entrevista de Mantenimiento Centrado en Fiabilidad (RCM)
en español, y entrega el Excel que el ingeniero necesita.**

Un análisis RCM serio es una entrevista larga con la gente que opera y mantiene el
equipo: qué hace la bomba, de cuántas maneras deja de hacerlo, qué pasa cuando falla,
y qué tarea de mantenimiento vale la pena. Hacerlo bien lleva días y exige a alguien
que domine el método. Hacerlo mal produce un plan de mantenimiento que nadie ejecuta.

Este proyecto pone un facilitador al otro lado del chat. Guía la conversación por las
seis fases del método, no deja avanzar con datos incompletos, y al final produce el
libro de Excel con las hojas AMEF y PLAN DE MANTENIMIENTO.

## La idea que lo sostiene: el modelo conversa, no calcula

El riesgo obvio de un agente así es que se invente los números. Aquí no puede:

**Todo cambio de estado pasa por una herramienta tipada.** El modelo no escribe en la
sesión; llama a `record_failure_mode`, `score_risk`, `run_decision_logic`. Si los datos
no cumplen las reglas, la herramienta rechaza la llamada y le dice qué falta, en
español, para que lo repregunte.

**Los cálculos son Python puro.** El RPN, el intervalo de búsqueda de fallas y la
cascada de decisión de SAE JA1011 viven en `engine/`, con sus propios tests. El modelo
nunca los produce ni los revisa.

**Las compuertas son del sistema, no del modelo.** No se pasa de fase ni se exporta el
entregable definitivo si el análisis está incompleto: la herramienta devuelve la lista
de lo que falta y la fase no avanza. El agente no puede saltárselo por complacencia.

**Lo que compromete a una persona se lo pregunta a una persona.** Una consecuencia de
seguridad o ambiente exige confirmación humana explícita, que queda firmada en el libro
de auditoría con quién la aprobó.

## Lo que hace, en concreto

- **Entrevista guiada de seis fases** — alcance y contexto → funciones → AMEF (modos,
  efectos, causas) → riesgo → decisión RCM → plan de mantenimiento.
- **FMEA según SAE J1739** y lógica de decisión según **SAE JA1011/JA1012**, con la
  taxonomía de modos de falla de **ISO 14224**.
- **Cálculo del intervalo de búsqueda de fallas (FFI)** por cinco métodos, para las
  fallas ocultas — las que nadie nota hasta que se necesita el dispositivo y no está.
- **Entregable Excel** con las hojas AMEF, PLAN DE MANTENIMIENTO, SAE-J1739 y
  AUDITORIA RCM. Borrador en cualquier momento; definitivo solo con el análisis
  completo.
- **Sesiones reanudables** — la entrevista dura días, no minutos. El estado persiste y
  el agente retoma sabiendo lo ya registrado, sin repreguntarlo.
- **Página de chat lista para compartir** en `/demo`, para que alguien lo pruebe con un
  enlace y sin instalar nada.
- **Todo en español**, incluidos los rechazos del método y los fallos técnicos: quien
  usa esto es un ingeniero de mantenimiento, no un desarrollador.

## Puesta en marcha

Necesita [uv](https://docs.astral.sh/uv/) y una credencial de modelo.

```bash
uv sync --all-groups
cp .env.example .env       # y ponga su credencial — el fichero está comentado
uv run rcm-runbook         # AgentOS en http://localhost:7777
```

Abra `http://localhost:7777/demo` y empiece a hablar, o conecte la interfaz de
[os.agno.com](https://os.agno.com) apuntando a esa URL. La API también se puede usar
directamente: `POST /agents/facilitador-rcm/runs`. Salud: `GET /health`.

**Credenciales.** `.env.example` las documenta todas con ejemplos del formato. Las dos
que importan:

| Variable | Para qué |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` *o* `ANTHROPIC_API_KEY` | La credencial del modelo. **Obligatoria.** La primera se emite con `claude setup-token` y factura contra la suscripción; la segunda es de pago por token. |
| `OS_SECURITY_KEY` | Protege la API y las descargas. **Obligatoria si el servicio es alcanzable desde fuera** — sin ella queda abierto. Genérela con `openssl rand -base64 24`. |

Sin `DATABASE_URL` se usa SQLite en local. Para un despliegue cuyo disco no persiste
(contenedores que duermen), apúntela a un Postgres o perderá las sesiones entre
visitas.

## Adaptarlo a otro formato de Excel

El contrato con el libro de destino está congelado en
`src/rcm_runbook/data/benchmark_fixture.json`: encabezados literales, orden de
columnas y catálogos. Los modelos del dominio **y** los tests dorados consumen ese
mismo fichero, así que el modelo de datos y el entregable no pueden divergir sin que
un test lo diga.

Para apuntar a otro libro, ponga el suyo en `data/reference/` y regenere el fixture:

```bash
uv run python scripts/extract_benchmark.py   # lee data/reference/amef_benchmark.xls
uv run pytest                                # el diff del fixture sale en los tests
```

El libro de referencia con el que se desarrolló esto no se publica: es de un cliente.

## Verificación

```bash
uv run pytest                        # 669 tests, sin llamar al modelo
uv run ruff check src tests scripts  # estilo
uv run mypy src scripts              # tipos
uv run pytest -m eval                # eval conversacional (sí llama al modelo)
```

La suite corre entera **sin credenciales y sin `.env`**, que es como corre en CI.

Dos cosas que quizá no espere encontrar:

- **`scripts/mutar.py`** — prueba de mutación: rompe el código a propósito y exige que
  la suite lo note. Un test que no puede fallar no prueba nada, y esa diferencia no se
  ve leyéndolo. Comprueba que la línea base esté verde antes de medir, que el reemplazo
  aplique exactamente una vez, y desactiva la caché de bytecode — sin eso, una mutación
  de la misma longitud puede medirse contra el fichero sin mutar.
- **`scripts/verificar_en_produccion.py`** — ejecuta contra un despliegue real los
  criterios de aceptación que exigen un turno del modelo, y borra sus sesiones al
  terminar. Lo que no se puede decidir sin interpretar lenguaje no lo puntúa: lo imprime
  marcado para que lo lea una persona.

## Estructura

```
src/rcm_runbook/
├── models/      catálogos, entidades del dominio, y el agregado de sesión
├── engine/      RPN, cascada de decisión JA1011, FFI, compuertas de fase
├── export/      proyecciones a filas y escritura del .xlsx
├── agent/       las herramientas, las instrucciones en español, la fábrica
├── knowledge/   consulta del manual RCM
└── app.py       AgentOS, descargas, autenticación, página de demo
```

## Documentación

| Documento | Qué contiene |
|---|---|
| [`docs/GLOSARIO.md`](docs/GLOSARIO.md) | El lenguaje ubicuo: término en español ↔ código ↔ columna del Excel |
| [`docs/UAT_SCRIPT_ES.md`](docs/UAT_SCRIPT_ES.md) | Guion de aceptación, 50 criterios |
| [`docs/UAT_LIBRO_MAYOR_ES.md`](docs/UAT_LIBRO_MAYOR_ES.md) | Qué criterio cerró cada quién y **cómo** se verificó |
| [`docs/client_method_20_steps.md`](docs/client_method_20_steps.md) | El método de 20 pasos que implementa |

El libro mayor distingue lo observado en producción, lo visto en un navegador y lo que
solo tiene un test detrás. Son cosas distintas, y mezclarlas es como un proyecto acaba
creyéndose más probado de lo que está.

## Estado

Funciona y está en uso para demostraciones. Dos limitaciones conocidas, documentadas en
el guion de aceptación: el agente a veces necesita que se le pida el borrador dos veces
para llamar a la herramienta de exportación —el botón de la página es el camino
garantizado—, y la semántica exacta de dos códigos de política del catálogo está
pendiente de confirmar con quien lo definió.

## Licencia

Apache 2.0 — ver [LICENSE](LICENSE).
