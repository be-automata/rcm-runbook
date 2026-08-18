# Glosario — Lenguaje ubicuo del proyecto RCM Runbook

Este documento tiene **dos partes con públicos distintos**, y conviene no
confundirlas:

1. **El contrato de terminología** — cómo habla el agente. Es lo único de aquí
   que está CONECTADO a su contexto, y vive de verdad en
   `src/rcm_runbook/agent/instructions_es.py`. Esta sección lo explica y
   argumenta; la fuente de verdad ejecutable es el prompt.
2. **La tabla de correspondencia** — término ↔ identificador ↔ columna ↔
   herramienta. Es documentación para quien programa. **No** está conectada al
   agente, y no debería estarlo: una tabla de 25 filas no cabe en un prompt que
   se inyecta en cada turno, y no gobierna cómo se habla.

Por qué la separación importa: meter la tabla en `_SOURCES` la volvería buscable
vía `consult_handbook`, o sea dependiente de que el agente decida consultarla. El
repo ya pagó ese modo de fallo una vez —`factory.py` lo documenta: «31 turnos, 0
modos de falla registrados»— y por eso las reglas de habla van en el prompt.

---

## 1. Contrato de terminología (español de España)

Mercado: **España**. Referencia normativa: **UNE-EN 13306**, *Mantenimiento.
Terminología del mantenimiento*.

| Concepto | Término | Apartado |
|---|---|---|
| failure | **fallo** — el EVENTO: cese de la aptitud para cumplir una función | 5.1 |
| fault | **avería** — el ESTADO que sigue al fallo | 6.1 |
| failure mode | **modo de fallo** («modo de avería» queda desaconsejado) | 5.2 |
| hidden failure | **fallo oculto** | 5.12 |
| spare part | **repuesto** | 3.5 |
| standby | **estado de espera** / **redundancia en espera** | 6.11 / 4.8 |

La nota 5.1 es literal: *«El "fallo" es un evento que se debe diferenciar de la
"avería", que es un estado»*. De ahí la regla que más fácil se incumple: en RCM
lo oculto es el **fallo**, no la avería, y decir «avería oculta» cambia el
concepto, no el registro.

**Dos avisos de atribución.** `fallo funcional`, `intervalo P-F` y
`failure finding` **no** están en la 13306: vienen de SAE JA1011/JA1012. Y **no
existe ISO 14224 en español** — `UNE-EN ISO 14224` está ratificada, no traducida,
así que el agente nunca debe decir «según ISO 14224, en español se dice X».

### Equivalencias de los términos que se filtran

| Inglés | En España | Nota |
|---|---|---|
| `standby` | «en reserva» (el equipo) / «en espera» (el modelo) | «de respaldo» es calco |
| `P-F interval` | «intervalo P-F» | no se deja en inglés |
| `failure finding` | «búsqueda de fallos ocultos» | **nunca** «búsqueda de averías»: eso es *troubleshooting* |
| `spare` | «repuesto» | término normativo |
| `FFI` | sigla, glosada la primera vez | |

### Lo que NO se traduce: el dialecto del cliente

Encabezados, nombres de hoja y valores del MENU van al Excel verbatim y **se
citan entre comillas sin adaptarlos**: la columna "Falla Funcional", la hoja
"AMEF", la política "Operar hasta la falla".

No es estilo. Los valores del catálogo son lo que el interesado teclea y lo que
acaba en su CMMS; si el agente hispaniza "Búsqueda de Falla" y él lo copia, el
validador lo rechaza. La asimetría se declara una vez al empezar en vez de
disimularse.

Siglas del libro con su equivalente español la primera vez: "AMEF" (AMFE),
"RPN" (NPR), "TPEF" (tiempo medio entre fallos, MTBF).

### Frecuencias: siempre glosadas en horas

«"Bi-Anual" (en su catálogo, cada 2 años = 17.520 h)». La RAE define *bianual*
como «dos veces al año» y en este catálogo vale dos años: factor 4 en la
dirección insegura. Igual con "Tri-Anual" y "Tetra-Anual". La etiqueta es del
cliente y no se toca; la defensa es decir el número.

---

## 2. Tabla de correspondencia (para quien programa — NO conectada al agente)

| Término (ES) | Identificador en código | Columna Excel | Herramienta/argumento |
|---|---|---|---|
| Falla funcional | `FunctionalFailure` | "Falla Funcional" | `record_functional_failure` |
| Modo de falla | `FailureMode` | "Modo de Falla (ISO 14224)" | `record_failure_mode` |
| Mecanismo de falla | `mechanism` | "Mecanismo de Falla (ISO 14224)" | argumento de `record_failure_mode` |
| Causa de la falla | `cause` | "Causa de la Falla (ISO 14224)" | argumento de `record_failure_mode` |
| Causa raíz | `root_cause` | "Causa Raíz" | argumento de `record_failure_mode` |
| Patrón de falla | `FailurePattern` | "Patrón de Falla" | valores del MENU: `Mortalidad Infantil`, `Aleatoria`, `Fin de Vida Útil`, `Aleatoria/Fin de Vida Útil` |
| Efecto de la falla | `Effect` | "Efecto de la Falla" | descripción local → sistema → planta |
| Falla evidente / falla oculta | `EvidentRoute` / `HiddenRoute` | "Falla Evidente (ABCD)" / "Falla Oculta (AEFG)" | rutas del diagrama de selección SAE JA-1012 |
| Consecuencia: Seguridad | flag `safety` | "Seguridad" | bandera de consecuencia |
| Consecuencia: Ambiente | flag `environment` | "Ambiente" | bandera de consecuencia |
| Consecuencia: Operacional | flag `operational` | "Operacional" | bandera de consecuencia |
| Consecuencia: No Operacional | flag `non_operational` | "No Operacional" | bandera de consecuencia |
| Estrategia de mantenimiento | `MaintenancePolicy` | "Estrategia de Mantenimiento" | códigos: `MBC`, `MBT`, `OHF`, `Rd`, `BF`, `ReP`, `ExEd`, `CC` (ver etiquetas abajo) |
| Severidad | `RiskScore.severity` | "Severidad" | `score_risk` |
| Ocurrencia | `RiskScore.occurrence` | "Ocurrecia" *(sic, sin la segunda "n" en el Excel)* | `score_risk` |
| Detección | `RiskScore.detection` | "Deteccion" *(sic, sin tilde en el Excel)* | `score_risk` |
| RPN (Número de Prioridad de Riesgo) | `RiskScore.rpn` | "RPN" | `score_risk` (RPN = S × O × D) |
| TPEF (Tiempo Promedio Entre Fallas) | `TPEFEstimate` | "TPEF (hrs)" (hoja PLAN) | fuente: `OREDA` / `historial` / `opinión de experto` |
| Tarea de mantenimiento | `MaintenanceTask` | "TAREA DE MANTENIMIENTO" | `record_task` |
| Frecuencia de la tarea | `Frequency` | "FRECUENCIA DE LA TAREA" | valores del MENU: Diario, Semanal, Catorcenal, Quinquenal, Mensual, Bimestral, Trimestral, Tetramestral, Semestral, Anual, Bi-Anual, Tri-Anual, Tetra-Anual, Quinque-Annual, Parada de Planta, Arranque, Según sea el caso |
| Duración de la tarea | `duration_hours` | "DURACION DE LA TAREA (HORAS)" | argumento de `record_task` |
| Ejecutor (disciplina) | `discipline` | "EJECUTOR (DISCIPLINA)" | valores: Mecánico, Electricista, Rotativo, Predictivo, Estatico, Operador, Instrumentista |
| Requiere paro del equipo | `requires_shutdown` | "REQUIERE PARO DEL EQUIPO?" | argumento de `record_task` (Sí/No) |
| Descarte por no credibilidad | `non_credible_discard` | — (el modo no se lleva adelante) | aplica SOLO a modos de falla no creíbles; **NUNCA llamar "descarte" a ReP** |

## Etiquetas de la Estrategia de Mantenimiento (hoja MENU)

| Código | Etiqueta (MENU) |
|---|---|
| `MBC` | Mantenimiento basado en Condición |
| `MBT` | Mantenimiento basado en Tiempo |
| `OHF` | Operar hasta la falla |
| `Rd` | Rediseño |
| `BF` | Búsqueda de Falla |
| `ReP` | Relubricación programada |
| `ExEd` | Exploración de edad |
| `CC` | Control de Calidad |

## Reglas de terminología

1. **Los efectos se describen ASUMIENDO que NO se hace mantenimiento.** La narrativa de "Efecto de la Falla" (local → sistema → planta) describe lo que sucedería sin ninguna tarea preventiva ni detectiva vigente; los controles actuales se documentan aparte.
2. **Causa ≠ modo.** El modo de falla es el evento observable (p. ej., "falla en arrancar", código ISO 14224 `FTS`); la causa es el porqué (p. ej., "bobinado quemado por sobrecarga"). No mezclar los campos "Modo de Falla (ISO 14224)" y "Causa de la Falla (ISO 14224)".
3. **Las funciones llevan estándar cuantitativo.** Toda función se redacta como verbo + objeto + estándar de desempeño medible; sin estándar cuantitativo no puede definirse objetivamente la falla funcional.
4. **"Descarte" solo para modos no creíbles.** El término "descarte" (`non_credible_discard`) se reserva para modos de falla que no se llevan adelante por no ser creíbles. `ReP` NO es un descarte: es **Relubricación programada**, una estrategia de mantenimiento válida.
