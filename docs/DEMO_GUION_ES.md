# Guion de demo — Facilitador RCM (audiencia no técnica)

**Duración:** 15–20 min · **Caso:** bomba centrífuga de crudo **P-03070** (espejo del
AMEF benchmark del cliente) · **Formato:** conversación en vivo + entregable Excel

---

## Antes de la demo (5 min, una sola vez)

El sistema está publicado en Cloudflare; no hay que levantar nada.

```bash
uv run python scripts/demo_seed.py    # plan B: data/exports/demo/AMEF_P-03070.xlsx
curl -s -o /dev/null -w '%{http_code}\n' https://rcm-demo.beautomata.com/health   # 200
```

Abra el chat en `https://rcm-demo.beautomata.com/demo?key=<OS_SECURITY_KEY>` y tenga
abierto en otra pestaña el Excel **plan B** (`data/exports/demo/AMEF_P-03070.xlsx`)
por si la red o el modelo fallan en vivo.

> **Despierte el contenedor unos minutos antes.** Duerme tras 20 min sin tráfico y
> la primera petición tarda bastante más; delante del cliente eso parece un cuelgue.

---

## Mensaje clave para abrir (30 s)

> «Hoy un análisis RCM toma semanas de talleres con un facilitador experto y termina
> en un Excel que alguien tiene que transcribir. Esto que van a ver es un facilitador
> de IA que **entrevista** al equipo en español, **no deja pasar errores de método**,
> y al final **genera el mismo Excel que ya usa la empresa** — con auditoría completa.»

---

## Acto 1 — La entrevista (5 min)

Pegue en el chat, uno por uno:

1. `Hola, soy Carlos de mantenimiento. Queremos hacer el análisis RCM de la bomba de crudo P-03070.`
   *Qué señalar:* el agente responde en español, pregunta UNA cosa a la vez (TAG,
   límites, contexto), como lo haría un facilitador senior.

2. `La bomba transfiere crudo del tanque TK-101 al múltiple, 850 GPM a 150 psi, sin bomba de respaldo. El equipo somos yo por mantenimiento y María Torres por operaciones.`
   *Qué señalar:* registra todo con herramientas (no "recuerda": **guarda**). Puede
   pedirle «muéstrame el avance» → responde con el estado real de la sesión.

3. **El momento "no me dejas hacer trampa" №1:**
   `La función de la bomba es bombear bien el crudo.`
   *Qué pasa:* el agente **rechaza** "bien" y exige un estándar medible
   («¿cuántos GPM? ¿a qué presión?»). Explique: *el método exige funciones
   cuantificadas; el agente no acepta vaguedades — eso es lo que separa un RCM
   auditable de una lluvia de ideas.*

## Acto 2 — El método que se hace respetar (5 min)

4. `Un modo de falla es la cavitación porque el tanque baja de nivel y el filtro de succión se tapa. Otro: fuga del sello mecánico si arrancan la bomba en seco.`
   *Qué señalar:* clasifica cada modo con el **código ISO 14224 del catálogo del
   cliente** (LOO, ELP…) — el mismo menú del Excel de la empresa.

5. **Momento №2 — efectos sin trampa:**
   `Si se tapa el filtro no pasa nada, porque el preventivo lo detecta antes.`
   *Qué pasa:* el agente repregunta «¿y si nadie interviene?» — el método exige
   describir el efecto **sin asumir mantenimiento**.

6. **Momento №3 — la seguridad exige un humano:**
   Cuando la fuga del sello (derrame, riesgo de incendio) llega a la decisión, el
   agente **se detiene y exige nombre y cargo de quien aprueba**. Diga:
   *«La IA no decide sola nada que toque seguridad o ambiente. Queda registrado
   quién aprobó, en la hoja de auditoría.»*
   Responda: `Aprueba María Torres, supervisora de operaciones.`

7. *Qué señalar en las decisiones:* la política (monitoreo por condición, búsqueda
   de fallas, etc.) **no la elige el modelo de IA** — la calcula un motor
   determinístico con las reglas SAE JA1011. El RPN es aritmética (S×O×D con las
   tablas SAE del cliente), y el intervalo de prueba del instrumento oculto sale de
   una **fórmula** (FFI), no de una opinión.

## Acto 3 — El entregable (3 min)

8. `Genera el entregable.`
   - Si faltan datos: el agente **se niega** y lista lo que falta (¡eso también es
     demo!: no existe el Excel a medias).
   - Con todo completo: exporta y da el enlace de descarga
     (`/exports/<sesión>/AMEF_P-03070.xlsx`).

9. Abra el Excel junto al AMEF original del cliente:
   - Hoja **AMEF**: mismas 27 columnas, mismos encabezados, menús desplegables con
     el catálogo del cliente.
   - Hoja **PLAN DE MANTENIMIENTO**: tareas con frecuencia, duración y ejecutor,
     listas para el CMMS.
   - Hoja **AUDITORIA RCM**: quién aprobó qué, justificación de cada decisión,
     modos descartados con su razón — *trazabilidad que hoy no existe*.

**Plan B:** si algo falla en vivo, muestre `data/exports/demo/AMEF_P-03070.xlsx`
(el mismo caso, generado por el mismo motor) y siga el guion sobre el Excel.

---

## Cierre (1 min)

> «Lo que tarda semanas de taller quedó en una conversación. El conocimiento del
> método está en el sistema, no en la memoria del facilitador; nada sale sin pasar
> las compuertas del método; y el resultado es el formato que la empresa ya usa.»

## Preguntas frecuentes (respuestas de bolsillo)

| Pregunta | Respuesta |
|---|---|
| ¿La IA puede inventarse números? | No: RPN, intervalos y políticas los calcula código determinístico probado (125 tests). La IA solo conversa. |
| ¿Y si el equipo se equivoca? | Las compuertas rechazan datos incompletos o mal formados, y todo cambio posterior invalida las decisiones viejas (hay que re-evaluar). |
| ¿Quién aprueba temas de seguridad? | Siempre una persona, con nombre y cargo, registrado en la hoja de auditoría. |
| ¿Dónde quedan los datos? | En una base de datos propia y privada (Postgres); nada se comparte con terceros ni se usa para entrenar modelos. |
| ¿Funciona con nuestro Excel? | El formato del entregable se congeló a partir del AMEF real de la empresa; si cambia, se re-congela con un script. |
| ¿Se puede retomar una sesión a medias? | Sí: misma sesión, otro día, el estado completo se restaura. |
