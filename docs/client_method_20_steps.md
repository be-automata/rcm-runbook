# Método del cliente: análisis RCM basado en SAE J1739 en 20 pasos

Referencia estructurada del método propio del cliente ("Pasos para elaborar un análisis RCM basado en SAE J1739"), contrastado con la teoría RCM (fuente: `docs/rcm_handbook_com.md`).

## Introducción: J1739 vs. JA1011/JA1012

- **SAE J1739** es un estándar de **FMEA/AMEF** (Análisis de Modos y Efectos de Falla) originado en la industria automotriz. Aporta las tablas de valoración Severidad/Ocurrencia/Detección (escala 1–10) y el RPN.
- **RCM propiamente dicho** está definido por **SAE JA1011** (criterios de evaluación de procesos RCM: las 7 preguntas) y **SAE JA1012** (guía de aplicación, incluido el diagrama de selección de estrategias).
- El método del cliente combina ambos: usa el AMEF de J1739 como base analítica (pasos 5–12) y la lógica de decisión RCM de JA1011/JA1012 para clasificar consecuencias y seleccionar políticas de mantenimiento (pasos 13–17).
- Las 7 preguntas de RCM: (1) funciones y estándares de desempeño en el contexto operacional actual; (2) fallas funcionales; (3) modos de falla; (4) qué sucede cuando ocurre cada falla (efectos); (5) en qué sentido importa cada falla (consecuencias); (6) qué tarea proactiva es aplicable y efectiva; (7) qué hacer si no hay tarea proactiva adecuada.

---

## Los 20 pasos

### Paso 1 — Definir el alcance

- **Propósito:** delimitar qué activos, sistemas o equipos serán analizados y hasta qué nivel de detalle (taxonomía).
- **Entradas:** criticidad de activos, objetivos del negocio, límites de la instalación.
- **Salidas:** lista de equipos/sistemas en alcance, fronteras del análisis, nivel taxonómico.
- **Preguntas del facilitador:**
  - ¿Qué equipos o sistemas entran en el análisis y cuáles quedan explícitamente fuera?
  - ¿Cuáles son los límites físicos del sistema (dónde empieza y termina)?
  - ¿A qué nivel de la taxonomía se analizará (planta, sistema, equipo, componente)?

### Paso 2 — Conformar el equipo multidisciplinario

- **Propósito:** asegurar que el análisis incorpore conocimiento de operación, mantenimiento e ingeniería.
- **Entradas:** organigrama, disponibilidad del personal.
- **Salidas:** equipo con roles definidos (facilitador, operadores, mantenedores por disciplina, ingeniería, seguridad/ambiente).
- **Preguntas del facilitador:**
  - ¿Quién opera este equipo día a día y quién lo mantiene?
  - ¿Contamos con representantes de todas las disciplinas relevantes (mecánica, eléctrica, instrumentación, operación)?
  - ¿Quién tiene la memoria histórica de fallas de este equipo?

### Paso 3 — Recopilar información técnica e histórica

- **Propósito:** reunir la documentación y los datos de fallas que sustentarán el análisis.
- **Entradas:** manuales del fabricante, P&IDs, hojas de datos, historial CMMS, bases genéricas (OREDA, ISO 14224).
- **Salidas:** paquete de información técnica validado y disponible para el equipo.
- **Preguntas del facilitador:**
  - ¿Qué documentación técnica existe y está actualizada?
  - ¿Qué historial de fallas y órdenes de trabajo tenemos de este equipo?
  - ¿Qué fuentes genéricas (OREDA) aplican si el historial propio es escaso?

### Paso 4 — Definir el contexto operacional

- **Propósito:** describir cómo, dónde y bajo qué condiciones opera el activo, pues las funciones y consecuencias dependen del contexto.
- **Entradas:** régimen de operación (continuo/intermitente), redundancias, condiciones ambientales, estándares de calidad y regulatorios.
- **Salidas:** documento de contexto operacional del sistema.
- **Preguntas del facilitador:**
  - ¿El equipo opera en continuo o por demanda? ¿Cuántas horas al año?
  - ¿Existe redundancia o respaldo? ¿Qué pasa aguas arriba y aguas abajo si se detiene?
  - ¿Qué condiciones ambientales o regulatorias condicionan su operación?

### Paso 5 — Definir las funciones

- **Propósito:** enunciar lo que el usuario quiere que el activo haga, con estándar de desempeño medible.
- **Entradas:** contexto operacional, especificaciones de diseño.
- **Salidas:** lista de funciones **primarias**, **secundarias** y **de protección**, redactadas en formato **verbo + objeto + estándar cuantitativo** (p. ej., "Bombear agua de enfriamiento a no menos de 1 bar y 100 m³/h").
- **Preguntas del facilitador:**
  - ¿Para qué existe este equipo en este contexto? (función primaria)
  - ¿Qué más se espera de él: contención, control, apariencia, seguridad, economía? (funciones secundarias y de protección)
  - ¿Cuál es el estándar cuantitativo mínimo aceptable de desempeño? ¿La capacidad de diseño supera lo que el proceso exige?

### Paso 6 — Identificar las fallas funcionales

- **Propósito:** definir de qué maneras el activo puede dejar de cumplir cada función (falla total o parcial).
- **Entradas:** lista de funciones con estándares cuantitativos.
- **Salidas:** fallas funcionales por función (p. ej., "Incapaz de bombear", "Bombea a menos de 1 bar").
- **Preguntas del facilitador:**
  - ¿Cómo puede este equipo dejar de cumplir totalmente esta función?
  - ¿Puede cumplirla parcialmente, por debajo del estándar? ¿Cuenta eso como falla?
  - ¿Puede hacer algo que no debería (falla por exceso)?

### Paso 7 — Identificar los modos de falla

- **Propósito:** listar los eventos que causan cada falla funcional, con granularidad **accionable** (ni tan general que no permita decidir, ni tan detallada que sea inmanejable).
- **Entradas:** fallas funcionales, historial, códigos **ISO 14224** de modos de falla (FTS, STP, UST, BRD, HIO, etc.).
- **Salidas:** modos de falla codificados según ISO 14224 por cada falla funcional.
- **Preguntas del facilitador:**
  - ¿Qué eventos han causado esta falla funcional aquí o en equipos similares?
  - ¿Es razonablemente probable (creíble) este modo en este contexto?
  - ¿El nivel de detalle permite decidir una tarea concreta de mantenimiento?

### Paso 8 — Describir los efectos de la falla

- **Propósito:** describir qué sucede cuando ocurre cada modo de falla, en cascada **local → sistema → planta**, **ASUMIENDO que NO se hace ningún mantenimiento** ni existe tarea preventiva vigente.
- **Entradas:** modos de falla, contexto operacional.
- **Salidas:** narrativa de efectos por modo (evidencia de la falla, impacto en producción, seguridad, ambiente, tiempo de reparación).
- **Preguntas del facilitador:**
  - Si no hiciéramos nada de mantenimiento, ¿qué pasaría al ocurrir esta falla?
  - ¿Cómo se evidencia la falla localmente, qué le pasa al sistema y qué le pasa a la planta?
  - ¿Cuánto tiempo tomaría restablecer la función? ¿Hay daño secundario?

### Paso 9 — Identificar las causas

- **Propósito:** determinar por qué ocurre cada modo de falla. **La causa NO es el modo**: el modo es el evento observable (p. ej., "no arranca"), la causa es el porqué (p. ej., "bobinado quemado por sobrecarga"). Se distinguen mecanismo, causa y causa raíz.
- **Entradas:** modos de falla, mecanismos ISO 14224, análisis de causa raíz previos.
- **Salidas:** mecanismo de falla, causa de la falla y causa raíz por cada modo; patrón de falla asociado (mortalidad infantil, aleatoria, fin de vida útil).
- **Preguntas del facilitador:**
  - ¿Por qué ocurre este modo de falla? ¿Cuál es el mecanismo físico (desgaste, corrosión, fatiga)?
  - ¿Cuál es la causa raíz (diseño, operación, mantenimiento, materiales)?
  - ¿Estamos confundiendo el síntoma (modo) con la razón (causa)?

### Paso 10 — Documentar los controles actuales

- **Propósito:** registrar qué se hace hoy para prevenir, detectar o mitigar cada modo de falla.
- **Entradas:** plan de mantenimiento vigente, rutinas de operación, sistemas de protección instalados.
- **Salidas:** controles clasificados como **preventivos**, **detectivos** y **mitigantes** por modo de falla.
- **Preguntas del facilitador:**
  - ¿Qué tareas del plan actual atacan este modo de falla?
  - ¿Existen alarmas, protecciones o inspecciones que lo detectan antes o durante?
  - ¿Qué mitigaría las consecuencias si ocurre de todos modos?

### Paso 11 — Valorar Severidad, Ocurrencia y Detección (S/O/D)

- **Propósito:** cuantificar el riesgo de cada modo de falla con las tablas de **SAE J1739**, escala **1–10** para cada factor.
- **Entradas:** efectos (para S), historial/TPEF (para O), controles detectivos actuales (para D), tablas J1739.
- **Salidas:** valores S, O y D por modo de falla.
- **Preguntas del facilitador:**
  - ¿Qué tan grave es el peor efecto creíble de esta falla? (Severidad)
  - ¿Con qué frecuencia ha ocurrido o se espera que ocurra? (Ocurrencia)
  - ¿Qué tan probable es que los controles actuales la detecten antes de que importe? (Detección: 10 = indetectable)

### Paso 12 — Priorizar (RPN)

- **Propósito:** ordenar los modos de falla para asignar esfuerzo de análisis y recursos.
- **Entradas:** valores S/O/D.
- **Salidas:** **RPN = S × O × D** por modo; lista priorizada. **Regla: una Severidad alta siempre se atiende**, aunque el RPN resulte bajo por O o D favorables.
- **Preguntas del facilitador:**
  - ¿Qué modos concentran el mayor RPN?
  - ¿Hay modos con Severidad alta (seguridad/ambiente) que el RPN esté "escondiendo"?
  - ¿Dónde fijamos el umbral de acción?

### Paso 13 — Clasificar las consecuencias

- **Propósito:** aplicar la lógica RCM (JA1012) para clasificar cada modo según el tipo de consecuencia, lo que determina la estrategia admisible.
- **Entradas:** efectos, contexto operacional.
- **Salidas:** clasificación en una de cuatro categorías: **Oculta**, **Seguridad/Ambiente**, **Operacional**, **No operacional**; registro de rutas del diagrama (Falla Evidente ABCD / Falla Oculta AEFG) y banderas Seguridad/Ambiente/Operacional/No Operacional.
- **Preguntas del facilitador:**
  - ¿La falla será evidente para el operador en condiciones normales de operación? (si no, es **oculta**)
  - ¿Puede lesionar personas o dañar el ambiente o incumplir normativa? (Seguridad/Ambiente)
  - ¿Afecta producción, calidad o costos operativos? (Operacional) ¿O solo el costo de la reparación? (No operacional)

### Paso 14 — Seleccionar la política de gestión de fallas (RCM)

- **Propósito:** elegir la estrategia técnicamente aplicable y económicamente efectiva para cada modo, según su clasificación de consecuencias.
- **Entradas:** clasificación del paso 13, patrón de falla, intervalo P-F, TPEF, vida útil (η).
- **Salidas:** política asignada por modo de falla, con uno de los códigos:
  - **MBC** — Mantenimiento basado en Condición
  - **MBT** — Mantenimiento basado en Tiempo (restauración o sustitución programada)
  - **BF** — Búsqueda de Fallas (solo fallas ocultas)
  - **Rd** — Rediseño
  - **ReP** — Relubricación programada
  - **ExEd** — Exploración de edad
  - **CC** — Control de Calidad
  - **OHF** — Operar hasta la falla

**Orden del árbol de decisión** (cascada de deseabilidad, se toma la primera estrategia aplicable y efectiva):

1. **¿Evidente u oculta?** Determina la rama del diagrama (Evidente ABCD / Oculta AEFG).
2. **¿Tipo de consecuencia?** Seguridad/Ambiente → Operacional → No operacional.
3. **Cascada de tareas**, en orden:
   1. **Monitoreo / mantenimiento basado en condición (MBC):** aplicable si existe una condición detectable con **intervalo P-F suficiente**; la inspección se programa con **intervalo ≤ P-F/2**.
   2. **Restauración programada (MBT):** aplicable si hay edad de desgaste identificable y la restauración devuelve la resistencia a la falla.
   3. **Sustitución programada (MBT):** igual criterio, reemplazando el componente.
   4. **Búsqueda de fallas (BF):** solo para **fallas ocultas** sin tarea proactiva aplicable; verifica periódicamente si la función de protección sigue disponible.
   5. **Rediseño (Rd):** **obligatorio si la consecuencia es de Seguridad/Ambiente y no se encontró ninguna tarea aplicable y efectiva**; opcional (justificación económica) en los demás casos.
   6. **Operar hasta la falla (OHF):** aceptable solo si no hay consecuencia de seguridad/ambiente y ninguna tarea proactiva es costo-efectiva.

**Reglas de intervalo:**

- Inspección por condición: **intervalo ≤ P-F/2** (garantiza al menos dos oportunidades de detección dentro del intervalo P-F).
- Restauración/sustitución programada: **frecuencia ≈ 0.9 · η** (90 % de la vida característica η, típicamente de un ajuste Weibull).

- **Preguntas del facilitador:**
  - ¿Existe un parámetro medible que anticipe esta falla? ¿Cuánto tiempo pasa entre la detección posible (P) y la falla funcional (F)?
  - ¿La falla tiene una edad de desgaste definida o es aleatoria? (patrón de falla)
  - Si es oculta y no hay tarea preventiva, ¿con qué frecuencia probaremos la función de protección?
  - Si es de seguridad/ambiente y nada aplica, ¿qué rediseño elimina o mitiga el riesgo?

### Paso 15 — Definir las acciones recomendadas

- **Propósito:** convertir la política seleccionada en acciones concretas (tareas, proyectos de rediseño, cambios de procedimiento).
- **Entradas:** política por modo, controles actuales (para no duplicar).
- **Salidas:** lista de acciones recomendadas con responsable y justificación.
- **Preguntas del facilitador:**
  - ¿Qué tarea concreta materializa esta política? ¿Quién debe ejecutarla?
  - ¿La acción es técnicamente aplicable en nuestra instalación?
  - ¿Reemplaza, complementa o elimina algún control actual?

### Paso 16 — Evaluar el riesgo residual

- **Propósito:** re-valorar S/O/D asumiendo implementadas las acciones, para verificar que el riesgo baja a nivel tolerable.
- **Entradas:** acciones recomendadas, valores S/O/D originales.
- **Salidas:** S/O/D y RPN residuales. **Regla: la Severidad es invariante salvo rediseño** — el mantenimiento reduce Ocurrencia y Detección, pero solo un cambio de diseño reduce la gravedad del efecto.
- **Preguntas del facilitador:**
  - Con la nueva tarea, ¿cuánto baja la Ocurrencia? ¿Y la Detección?
  - ¿El RPN residual queda bajo el umbral tolerable?
  - Si la Severidad sigue inaceptable, ¿se justifica el rediseño?

### Paso 17 — Elaborar el plan de mantenimiento

- **Propósito:** consolidar las tareas seleccionadas en un plan ejecutable.
- **Entradas:** acciones recomendadas, recursos disponibles, ventanas de paro.
- **Salidas:** plan con, por cada tarea: **descripción de la tarea, frecuencia, duración (horas), ejecutor (disciplina)**, **TPEF con su fuente (OREDA / historial propio / opinión de experto)** y si **requiere paro del equipo**.
- **Preguntas del facilitador:**
  - ¿Cada tarea tiene frecuencia, duración estimada y disciplina ejecutora asignada?
  - ¿De dónde sale el TPEF que sustenta la frecuencia: OREDA, historial o experto?
  - ¿La tarea exige parar el equipo? ¿Puede agruparse en una ventana de paro existente?

### Paso 18 — Validar con operaciones

- **Propósito:** confirmar con el personal de operación que el plan es viable y coherente con la realidad operativa.
- **Entradas:** plan de mantenimiento propuesto.
- **Salidas:** plan validado y aprobado; ajustes acordados.
- **Preguntas del facilitador:**
  - ¿Las frecuencias y ventanas de paro son compatibles con el programa de producción?
  - ¿Los operadores pueden asumir las tareas asignadas a "Operador"?
  - ¿Falta algún modo de falla que operaciones haya visto y el análisis no capturó?

### Paso 19 — Definir KPIs de seguimiento

- **Propósito:** establecer indicadores para medir la efectividad del plan.
- **Entradas:** plan aprobado, línea base histórica.
- **Salidas:** tablero de KPIs: **MTBF** (tiempo medio entre fallas), **MTTR** (tiempo medio de reparación), **disponibilidad**, **cumplimiento del plan**.
- **Preguntas del facilitador:**
  - ¿Cuál es la línea base actual de MTBF, MTTR y disponibilidad?
  - ¿Qué metas fijamos y en qué plazo?
  - ¿Quién mide, con qué frecuencia y desde qué sistema?

### Paso 20 — Revisión periódica

- **Propósito:** mantener el análisis vivo: los contextos, patrones de falla y TPEF cambian con el tiempo.
- **Entradas:** KPIs, nuevas fallas, cambios de contexto operacional o de diseño.
- **Salidas:** análisis actualizado; ciclo de mejora (los hallazgos de Exploración de edad y del historial retroalimentan los pasos 7–17).
- **Preguntas del facilitador:**
  - ¿Han ocurrido fallas no previstas en el análisis?
  - ¿Cambió el contexto operacional (régimen, redundancia, normativa)?
  - ¿Los datos reales confirman los TPEF y frecuencias asumidos? ¿Cuándo es la próxima revisión?
