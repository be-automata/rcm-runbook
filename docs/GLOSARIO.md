# Glosario — Lenguaje ubicuo del proyecto RCM Runbook

Tabla de correspondencia entre el término de dominio en español, su identificador en el código, la columna del Excel del cliente (ortografía exacta según `src/rcm_runbook/data/benchmark_fixture.json`, hoja AMEF) y la herramienta o argumento asociado.

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
