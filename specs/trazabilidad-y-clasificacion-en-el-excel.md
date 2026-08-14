# Trazabilidad y clasificación en el Excel exportado

> AUTOSUFICIENTE: ejecutable en una sesión nueva, por alguien que no
> participó de la conversación que la originó.

## 1. Alcance

Dos defectos del exportador hacen que el libro entregado no se pueda cruzar
con la conversación ni se pueda auditar fila por fila: el identificador del
modo de falla (`FM-xxx`) nunca llega al Excel, y las columnas de clasificación
evidente/oculta salen vacías en casi la mitad de las filas. En ambos casos el
dato ya existe en el estado de la sesión y se descarta al serializar. Esta
feature cierra los dos, más el descarte silencioso que hoy hace desaparecer
modos de la hoja PLAN sin dejar rastro.

Origen: UAT del 09–11 ago 2026 con el interesado —ingeniero de mantenimiento,
tester y product owner de la demo— sobre la sesión
`demo-7aa88eb4-0889-4a91-b7b5-6a5cd4a3edc9`. Esa ronda dejó cinco hallazgos,
que se citan por número en el resto del documento:

| # | Hallazgo |
|---|---|
| 1 | Los identificadores `FF-`/`FM-` no llegan al Excel |
| 2 | Modos sin clasificar evidente/oculta, sin razón visible |
| 3 | Informe con análisis costo-beneficio por actividad |
| 4 | Glosario de terminología; usar "fallo" en vez de "falla" |
| 5 | Colaboración asíncrona por correo entre miembros de la organización |

Esta spec cubre **1 y 2**. Van juntos porque tocan el mismo fichero y los
mismos golden tests: separarlos obliga a rehacer dos veces el mismo trabajo de
verificación.

El "borrador honesto" (tarea 6) puede parecer una tercera feature colada. Está
acá a propósito: los hallazgos 1 y 2 no se descubrieron sobre un entregable
definitivo sino sobre un **borrador** que el interesado tomó por terminado —
las tres exportaciones definitivas de esa sesión fueron correctamente
rechazadas por la compuerta y él nunca vio ninguna. Arreglar la trazabilidad y
la clasificación sin arreglar eso deja un libro mejor que se sigue leyendo como
final cuando no lo es, que es la mitad del daño. Si al planificar se decide
cortarlo igual, sacarlo entero: tarea 6, criterio 5 y este párrafo.

### Entra

- Columna A de las hojas `AMEF` y `PLAN DE MANTENIMIENTO` con el ID del modo
  (`FM-001`), fuera del rango de cabeceras congelado.
- Identificador de la falla funcional (`FF-xxx`) visible en la celda
  "Falla Funcional" de la hoja AMEF.
- Que "Falla Evidente (ABCD)" / "Falla Oculta (AEFG)" dejen de depender
  exclusivamente de que exista una decisión RCM.
- Que ningún modo creíble desaparezca de la hoja PLAN sin dejar rastro (hoy
  `rows.py:185-186` lo salta con `if decision is None: continue`; ojo que el
  `continue` de `rows.py:183-184` es otro, el de credibilidad, y ese se queda).
- Distinguir un borrador de un definitivo **dentro del libro**, no sólo por el
  nombre del fichero. Por fila se señala lo que el criterio 3 cubre (la ruta
  pendiente); el resto de los defectos se concentra en AUDITORIA RCM,
  identificado por `FM-id`. Ver la limitación declarada en el criterio 5.

### NO entra (explícito)

- Modificar los encabezados congelados ni el orden de columnas del rango del
  benchmark. `AMEFRow` y `PlanRow` no ganan ni pierden campos.
- Limpiar el estado de la sesión de UAT. Los 28 modos contaminados se muestran
  correctamente, no se corrigen aquí. La migración de datos es otra spec.
- El modelo de supersesión (`superseded_by`), la herramienta
  `supersede_failure_mode`, poder renombrar una falla funcional
  (`add_functional_failure` no tiene `reemplazar`, `session.py:327-337`), y
  elevar `_same_text` a `_casi_igual` en `add_failure_mode` (`session.py:349`).
  Es la causa raíz y necesita su propia spec; sin ella el problema se repite,
  pero arreglarla no rescata el entregable que el interesado ya tiene.
- Las 31 decisiones desactualizadas (ver Pre-requisitos). Hallazgo nuevo, sin
  diagnóstico todavía.
- Análisis costo-beneficio (hallazgo 3), glosario y terminología (hallazgo 4),
  colaboración asíncrona por correo (hallazgo 5).
- Dar al agente herramientas de red o búsqueda de costos en Internet (eso es
  del hallazgo 3). Esta exclusión es sobre **el producto**, no sobre el proceso
  de desarrollo: leer Neon para construir el fixture y desplegar para verificar
  son actividades normales de esta spec.
- Corregir que el agente afirme haber hecho cambios que no hizo. Durante el UAT
  aseguró dos veces que el libro ya traía columnas con los códigos —textual:
  *"el Excel que exporté ya contiene los códigos FF- y FM- en columnas
  separadas. El sistema los genera automáticamente cuando exporta"*— y era
  falso; el interesado tuvo que abrir el fichero y desmentirlo. Es un problema
  real y grave, pero es de prompt y no se arregla en el exportador.

## Pre-requisitos

- **RESUELTO — decisión sobre los 28 duplicados.** Se analizaron uno por uno.
  **20 son duplicados con sucesor identificado** en el rango `FM-033+`; **8 son
  huérfanos de verdad, sin reemplazo**: FM-006 (aislamiento del motor), FM-012
  (retención bloqueada abierta), FM-013 (deriva del transmisor), FM-020
  (entrada de aire), FM-021 (velocidad de giro baja), FM-025 (bypass en
  descarga), FM-026 (manómetro defectuoso), FM-031 (válvula de aislamiento
  cerrada). El rango nuevo **no es un superconjunto del viejo**: descartarlos
  en bloque borraría 8 modos que nadie reemplazó.

  Consecuencia para esta spec: **el exportador no oculta ni descarta nada**. Su
  trabajo es mostrar el estado real de forma legible; la limpieza es un
  problema de datos y de modelo, y va aparte. Concretamente se descartaron dos
  opciones que parecían razonables: marcarlos `credible=False` (miente sobre la
  naturaleza del descarte y corrompe la semántica JA1011 del campo
  `non_credible_discard`) y excluirlos de la exportación (generaliza al AMEF el
  mismo defecto de desaparición silenciosa que hoy tiene el PLAN, y oculta 14
  modos con consecuencia de seguridad o ambiente).

- **Contexto que esta spec no resuelve pero que condiciona su verificación.**
  `export_blockers()` sobre el estado real devuelve **121 bloqueadores**: 28
  modos sin decisión, **31 valoraciones desactualizadas y 31 decisiones
  desactualizadas**. Es decir, los 32 modos que sí tienen decisión tampoco son
  confiables. La sesión está en `phase=4`. Al verificar el criterio 3 no
  esperar un libro limpio: esperar un libro que **declare** con precisión qué
  está incompleto y por qué.
- **Estado real de la sesión de UAT, y hay que dejarlo dentro del repo.** Hoy
  sólo vive en Neon: esquema `ai`, tabla `agno_sessions`, fila
  `session_id = 'demo-7aa88eb4-0889-4a91-b7b5-6a5cd4a3edc9'`, campo
  `session_data -> session_state -> rcm`. `DATABASE_URL` está en `.env.deploy`
  (usar `postgresql://`; el valor guardado trae el prefijo
  `postgresql+psycopg://`, que `psycopg.connect` no acepta). Se carga con
  `RCMSession.model_validate(estado)`.

  Depender de una base externa viva para verificar una spec es frágil, así que
  la tarea 7 incluye **congelarlo como fixture versionado** en el repositorio.
  A partir de ahí la spec se verifica sin red. Si la fila ya no existiera en
  Neon cuando se ejecute esto, la spec sigue siendo implementable, pero los
  criterios 1, 3 y 4 pierden su línea base y habría que construir a mano un
  estado que cubra las cinco combinaciones (con decisión / sin decisión /
  oculto sin decisión / seguridad-ambiente sin decisión / no creíble).

## 3. Criterios de aceptación

Delivery a enterprise-grade product (executed, observed, and verified),
leverage on `.claude/agents/testing/production-validator.md` to run old and new UAT/Test cases in the local and target (remote) environment.

1. **Trazabilidad.** Regenerado el libro con el estado de la sesión de UAT,
   toda fila de la **tabla principal** de `AMEF` (desde `AMEF_HEADER_ROW + 1`)
   y de `PLAN DE MANTENIMIENTO` (desde `PLAN_HEADER_ROW + 1`) lleva en la
   columna A el ID del modo, y la celda "Falla Funcional" de AMEF empieza por
   el código `FF-xxx`. El acotamiento importa: la hoja PLAN tiene un bloque
   TPEF **encima** de su cabecera que ya escribe IDs en las columnas 14-17
   (`excel.py:387-404`) y cuya columna A queda vacía a propósito; ese bloque no
   entra en el criterio. Cualquier `FM-xxx` citado en la conversación se
   localiza en el libro sin leer descripciones.
2. **Contrato del dialecto intacto.** `amef_headers() == FIXTURE["amef"]["headers"]`
   y `plan_headers() == FIXTURE["plan"]["headers"]` siguen pasando **sin
   modificar el fixture ni los tests**. `tests/export/test_golden.py` pasa
   entero sin ediciones, salvo tests nuevos que se añadan.
3. **Sin celdas mudas y sin letras inventadas.** Ninguna fila de datos sale con
   "Falla Evidente (ABCD)" y "Falla Oculta (AEFG)" ambas vacías. Cubre los dos
   casos, no sólo el primero: modo **sin decisión**, y modo **con decisión pero
   sin ruta** — `DecisionResult.evident_route` y `hidden_route` son ambos
   opcionales (`domain.py:230-231`), así que un `DecisionResult` construido a
   mano o cargado de estado histórico puede no traer ninguna. (`derive_route`
   siempre devuelve exactamente una, así que las decisiones nacidas de
   `decide()` están cubiertas; el agujero es para las que no pasaron por ahí.)
   Y a la inversa, **toda letra impresa es reproducible**: para cada fila con
   ruta, `derive_route(effect, decision.policy)` (`decision_logic.py:81-100`)
   devuelve exactamente la letra que está en la celda. Se formula así, y no
   como "proviene de un `DecisionResult`", porque la procedencia no se puede
   demostrar leyendo el libro y porque `DecisionResult` no valida que la ruta
   sea coherente con la visibilidad ni con la política (`domain.py:224-238`):
   una `B` guardada a mano sobre un efecto de seguridad pasaría el criterio
   ingenuo. Recalcular sí lo detecta. Comprobado sobre la sesión de UAT: las 32
   decisiones existentes reproducen su letra 32/32 sin discrepancias, así que
   el criterio no arranca en rojo. Línea base actual: 28 de 60 filas mudas.
4. **Sin desapariciones silenciosas.** Por cada modo creíble sin decisión
   existe **al menos una fila** en la tabla principal de la hoja PLAN. Los no
   creíbles siguen fuera de AMEF y de PLAN y sólo aparecen en AUDITORIA RCM,
   que es el comportamiento actual y correcto (`rows.py:129-130`,
   `excel.py:185-191`). Línea base actual: AMEF 60 filas, PLAN 49, sin
   explicación de las 11 que faltan.
5. **Borrador honesto, y comprobable.** Abriendo un borrador sin leer el nombre
   del fichero se distingue de un definitivo. Concretamente: (a) el bloque de
   título lleva el sello `BORRADOR — NO APTO PARA EJECUCIÓN`; (b) la hoja
   AUDITORIA RCM lista **todos** los bloqueadores que devuelve
   `export_blockers()`, y **cada uno que se refiera a un modo lleva su `FM-id`
   en una celda propia**, de modo que un test pueda afirmar
   `{ids en la hoja} ⊇ {ids con bloqueador}` sin analizar prosa. Sobre la
   sesión de UAT eso son 121 bloqueadores.
   Limitación aceptada y declarada: la fila principal sólo señala por sí misma
   la ruta pendiente (criterio 3). Una valoración o decisión **desactualizada**
   —31 de cada una en esa sesión— no se distingue mirando su fila; hay que ir a
   AUDITORIA. Cerrar esa brecha exigiría una columna de estado que no existe y
   que no cabe sin tocar el rango del benchmark, así que queda fuera.
6. **Verificado donde corre.** Los criterios 1-5 se comprueban sobre un libro
   regenerado desde el estado real de la sesión de UAT, no sólo sobre el
   fixture sintético de dos modos. La comprobación **local**, contra el fixture
   versionado de la tarea 7, es condición de aceptación. La comprobación en el
   **entorno desplegado** es un paso operativo de cierre, no un bloqueo de
   implementación: depende de credenciales y de una ventana de despliegue, y no
   debe impedir dar por terminado el código si lo local está en verde.
7. **Sin regresión de la compuerta.** `check_gate` / `export_blockers` sigue
   rechazando lo que rechazaba antes. Esta feature no vuelve exportable nada
   que hoy no lo sea.

## 4. Notas de arquitectura

**Capas que toca:** `src/rcm_runbook/export/rows.py` (proyección) y
`src/rcm_runbook/export/excel.py` (escritura). El dominio no cambia: ni
`domain.py` ni `session.py` ganan campos. El motor de decisión tampoco.

**Restricción central y por qué condiciona todo el diseño.** `amef_headers()`
(`rows.py:224`) se construye leyendo los alias de `AMEFRow.model_fields`, y
`tests/export/test_golden.py:26-30` los compara verbatim contra
`src/rcm_runbook/data/benchmark_fixture.json`. Por lo tanto **añadir un campo
al modelo de fila rompe el contrato del dialecto del cliente**. El ID no puede
ser un campo de `AMEFRow` / `PlanRow`.

La salida está en que `_write_headers` (`excel.py:70-71`) y los bucles de
escritura (`excel.py:364-365`, `376-377`) arrancan en `column=2`: **la columna
A está libre en ambas hojas** y queda fuera del rango de encabezados del
benchmark. Ahí va el ID, escrito directamente por `excel.py`, sin pasar por el
modelo de fila. (Cuidado con la palabra "congelado": en esta spec designa
siempre el contrato de cabeceras contra el fixture, nunca `freeze_panes` —
que, como se explica más abajo, sí congela visualmente la columna A.)

**Cómo llega el ID al escritor sin duplicar la lógica de filtrado.** Hoy
`to_amef_rows` (`rows.py:126-128`) itera `session.failure_modes.items()`, liga
`fmid` y lo tira. Devolver tuplas rompería a los llamadores
(`test_golden.py:59-60` hace `amef[0].rpn`; `:51-55` hace `r.basado_condicion`).
El patrón que respeta lo existente es extraer un generador interno que emita
`(fmid, row)` y dejar `to_amef_rows` / `to_plan_rows` como proyecciones de ese
generador. Una sola fuente de verdad para el filtro de credibilidad y el orden,
firma pública intacta.

**Decisión tomada — el código `FF-` va dentro de la celda.** No hay una segunda
columna libre. El encabezado "Falla Funcional" está congelado, pero su
*contenido* no lo está: hoy es `ff.description` (`rows.py:141`) y ningún golden
test lo verifica (`test_data_row_values` comprueba TAG, código ISO, estrategia,
RPN y las banderas de consecuencia). El formato sale del pedido textual del
interesado durante el UAT: *"Vuelve a crear el Excel, redactando cada falla
funcional y modo de falla con el código correspondiente. Por ejemplo: FF-007
(Contaminación del agua) y FM-001 (Obstrucción del filtro o tubería de
aspiración), para facilitar su ubicación."* Se desvía del benchmark en
contenido, no en estructura, y es reversible.
La alternativa —no mostrar el `FF-`— deja el pedido a medias, porque el agente
cita ambos códigos en la conversación.

**Quién se queda con la columna A.** El ID. Es el pedido explícito del
interesado y no tiene otro lugar donde ir. La tentación es usarla también para
un marcador de estado (`⚠ SIN DECISIÓN`), pero eso sería redundante: el
centinela de la celda de ruta ya dice exactamente eso, en la columna donde el
lector busca la clasificación. Dos marcas para el mismo hecho, en la misma
fila, se desincronizan. Columna A = identificador, y nada más.

**Sobre rellenar ABCD/AEFG desde el `Effect`: no. Y ojo, no es código muerto.**
`rows.py:151` y `:155` ya tienen escrito ese respaldo hacia
`Effect.evident_route` / `hidden_route`. Es tentador justificar su borrado
diciendo que nunca dispara, y **sería impreciso**: los campos existen y son
válidos en el modelo (`domain.py:158-159`), y `set_effect(**kwargs)`
(`session.py:408-412`) los deja escribir **sin exigir una decisión RCM** — el
propio fixture `full_session()` los pone a mano. (Sí hay una validación, pero
sólo de coherencia con la visibilidad: `domain.py:165-171` rechaza una ruta
evidente en un efecto oculto y viceversa.) Lo que sí es cierto, y es un hecho distinto,
es que **el camino de producción no los puebla**: `record_effect` no los expone
(`tools.py:487-492`) y el único productor de rutas es `derive_route`, que
escribe sobre el `DecisionResult` (`decision_logic.py:226`, `:262`). Verificado
en los datos: 0 de 60 efectos de la sesión real traen ruta.

Por lo tanto el borrado es una **decisión semántica, no una limpieza**: la ruta
es una conclusión de la lógica JA1011 y su único dueño legítimo es
`DecisionResult`. Una ruta guardada en un `Effect` es un dato sin procedencia
auditable, y el respaldo actual la imprimiría como si tuviera la misma
autoridad que una decidida. Asumir el cambio de comportamiento para estados que
hoy son válidos es parte del objetivo, no un efecto colateral. **Se borra el
fallback, no se extiende.**

Y aunque se quisiera, no se puede derivar la letra sin la política:
`derive_route` (`decision_logic.py:81-100`) la toma como argumento y en dos de
sus cuatro ramas la letra depende de ella. Sobre los 28 reales: **14 son
determinables** (consecuencia de seguridad/ambiente → siempre `A`) y **14 son
ambiguos** (`B` vs `D`, `C` vs `D`, `E` vs `G`, según haya o no operar-hasta-la-
falla). Escribir `B` donde podría ser `D` es afirmar en el entregable que el
equipo descartó operar hasta la falla — una decisión que nadie tomó.

**El centinela de texto no choca con ningún desplegable.** Verificado:
`AMEF_COLUMN_VOCAB` y `PLAN_COLUMN_VOCAB` (`excel.py:130-157`) no incluyen
"Falla Evidente (ABCD)" ni "Falla Oculta (AEFG)", así que `_add_validation`
(`excel.py:118-127`) nunca les pone lista. Escribir texto libre ahí es seguro.
Si en el futuro se les añade validación, el centinela tiene que entrar en el
vocabulario o el libro empezará a marcar error en esas celdas.

**La columna A juega a favor por un detalle del código.** `excel.py:78` fija
`freeze_panes` en `(header_row+1, column=2)`: la columna A queda **congelada**,
o sea visible mientras se hace scroll horizontal por las 27 columnas. Es
justamente el comportamiento que hace útil un identificador. Ojo con el ancho:
`excel.py:77` sólo asigna ancho a las columnas del rango (desde la 2), así que
la A queda con el ancho por defecto y hay que fijárselo explícitamente.

Por eso el centinela es **uniforme**, incluso para los 14 con `A` forzosa.
Poner `A` en unos y texto en otros da una columna con dos tipos de dato y
sugiere que esa `A` salió de la lógica JA1011. La letra debe ser siempre
producto de un `DecisionResult`. Para los 14 críticos, "PENDIENTE" es una
llamada a la acción; "A (preliminar)" es una invitación a no mirar.

**En cuál de las dos columnas va el centinela.** En la que corresponde a la
visibilidad, que sí se conoce sin decisión: si `effect.is_hidden` es verdadero
va en "Falla Oculta (AEFG)" y "Falla Evidente (ABCD)" queda vacía; si es falso,
al revés. Nunca en ambas. Así la fila sigue comunicando lo que el análisis
**sí** determinó (la falla es oculta) y sólo declara pendiente lo que falta (la
letra de ruta, que depende de la política). Ponerlo en las dos columnas
destruiría esa distinción y volvería la clasificación ilegible. Caso borde: si
no hay `Effect` registrado, el centinela va en ABCD por convención y el libro
lo declara como tal — pero eso no debería ocurrir para un modo creíble que
llegó al AMEF.

**Fixture de regresión.** El fixture sintético actual (`full_session()`, que
vive en `tests/unit/test_compliance.py` y `test_golden.py:18` importa: dos
modos, ambos con decisión) no puede detectar ninguno de estos dos defectos: por
construcción no tiene modos sin decisión ni IDs que cruzar. Hace falta un
fixture derivado del estado real de la sesión de UAT, o los tests nuevos
pasarán en verde sobre un caso que nunca falla.

## 5. Tareas

1. [ ] Extraer de `to_amef_rows` / `to_plan_rows` un generador interno que
       emita `(fmid, row)`, dejando las dos funciones públicas como
       proyecciones. Sin cambio de comportamiento; `test_golden.py` pasa igual.
2. [ ] Escribir el ID del modo en la columna A de ambas hojas desde
       `excel.py`, con su encabezado en la misma fila que el resto. Verificar
       que los dos tests de cabecera verbatim siguen pasando.
3. [ ] Prefijar el código `FF-xxx` en la celda "Falla Funcional" de AMEF.
4. [ ] Eliminar el fallback a `Effect.*_route` de `rows.py:151` y `:155`, y
       escribir el centinela `PENDIENTE — sin decisión RCM` en la columna que
       marque `effect.is_hidden`, dejando la otra vacía. Cubrir los dos casos:
       sin decisión, y con decisión pero sin ninguna de las dos rutas.
       Verificado que no rompe golden tests: `test_data_row_values` no asserta
       sobre esas dos columnas y los 2 modos del fixture tienen decisión con
       ruta. Ojo: ese mismo fixture escribe rutas en el `Effect`
       (`test_compliance.py:73-85`), así que al quitar el fallback hay que
       comprobar que ningún test dependiera de esa ruta indirecta.
4b. [ ] **Contrastar la ruta guardada contra `derive_route` antes de
       imprimirla** — es lo que hace verificable el criterio 3. Regla: si
       coinciden, se imprime la letra; si no coinciden, **no se imprime
       ninguna** — va el centinela y el desacuerdo queda registrado en
       AUDITORIA RCM con su `FM-id`. El exportador nunca reescribe en silencio
       una conclusión del dominio (imprimir la recalculada ocultaría que el
       estado está corrupto) ni imprime una letra que no puede reproducir.
       Aplica a las dos hojas: `rows.py:149-155` y `rows.py:201-202`. Sobre la
       sesión de UAT no cambia nada —las 32 decisiones reproducen su letra
       32/32—, así que el efecto se ve sólo en estados históricos o construidos
       a mano, que es justamente el agujero que cierra.
5. [ ] Quitar el `continue` de `rows.py:185-186` (el de `decision is None`, no
       el de credibilidad de `:183-184`): un modo creíble sin decisión
       emite su fila en el PLAN, con las columnas de estrategia vacías y el
       mismo centinela. Desaparecer no es una opción en un entregable
       auditable — hoy se pierden 8 de las 11 fallas ocultas de la sesión y
       todas las de seguridad sin decidir.
6. [ ] Borrador honesto. **No es una edición local: hay que cablear el dato
       hasta donde se escribe.** Hoy `draft` sólo llega a `export_xlsx`
       (`excel.py:419`) y se usa para el prefijo del nombre (`:430`);
       `build_workbook(session)` (`excel.py:353`) ni siquiera lo recibe. Y
       `export_excel` no calcula `export_blockers()` cuando `draft=True`
       (`tools.py:992`), así que la lista de defectos ni existe en ese camino.
       Concretamente: pasar `draft` (y los bloqueadores) a `build_workbook`,
       estampar `BORRADOR — NO APTO PARA EJECUCIÓN` en el bloque de título
       (`excel.py:56-67`), y volcar los bloqueadores en AUDITORIA RCM. Definir
       en la implementación si los bloqueadores se calculan dentro de
       `export_xlsx` o se le pasan ya calculados.
7. [ ] Congelar el estado de la sesión de UAT como fixture versionado dentro
       del repo (junto a `src/rcm_runbook/data/benchmark_fixture.json`, que es
       el precedente del patrón) y añadir sobre él los tests de los criterios
       1, 3 y 4. A partir de esta tarea la spec se verifica sin acceso a Neon.
8. [ ] Verificar la implementación contra esta spec con el agente
       `spec-verifier` (`.claude/agents/spec-verifier.md`) **antes del PR**. Lo
       exige `.claude/rules/specs.md:22` para toda feature con spec, y es una
       comprobación distinta de la de la tarea 9: `spec-verifier` contrasta el
       código contra los criterios de este documento; `production-validator`
       ejecuta los casos de prueba.
9. [ ] Verificación con `production-validator`
       (`~/.claude/agents/testing/production-validator.md`) en local y en el
       entorno desplegado, regenerando el libro de la sesión de UAT y
       comprobando los siete criterios. El despliegue es Cloudflare Containers
       + Neon; el procedimiento está en `docs/DESPLIEGUE_CLOUDFLARE_ES.md`.
       Aviso operativo: con la VPN activa `wrangler` no puede desplegar, así
       que hay que desconectarla antes de esta tarea.

## Supuestos

- SUPUESTO: la columna A puede usarse libremente en ambas hojas. Verificado en
  el código (`excel.py:71`, `:365`, `:377` arrancan en `column=2`) y en un
  libro regenerado, pero no contra la plantilla original del cliente: si el
  cliente tiene macros o referencias absolutas que asuman que A está vacía,
  esto se cae y habría que revisar la decisión.
- SUPUESTO: el interesado quiere el `FF-` dentro de la celda y no en una
  columna aparte. Se basa en su pedido textual, citado en Notas de
  arquitectura. No fue reconfirmado después: más tarde en la misma sesión
  cedió —*"Continuemos con la Decisión RCM usando el Excel actual (sin códigos
  en columnas separadas) y dejamos la reformateo para después"*— pero eso fue
  para no bloquear el análisis, no un cambio de preferencia.
- SUPUESTO: "borrador honesto" (criterio 5) se resuelve dentro del exportador.
  Si se decide resolverlo en la interfaz de descarga, sale del alcance de esta
  spec.

## Anexo — los 20 duplicados con sucesor

Se registran acá para que no se pierdan: esta spec **no** los usa (el
exportador no oculta nada), pero son el insumo de la spec de migración de
datos. Pares `viejo → sucesor`, con el criterio con que se establecieron.

Descripción normalizada idéntica (verificado mecánicamente, alta confianza):
FM-001→FM-035, FM-002→FM-036, FM-003→FM-052, FM-004→FM-043, FM-007→FM-056,
FM-008→FM-058, FM-017→FM-041, FM-022→FM-060, FM-023→FM-040, FM-027→FM-047,
FM-030→FM-042, FM-032→FM-044.

Descripción muy próxima (similitud ≥ 0.85, revisado a mano): FM-009→FM-053,
FM-011→FM-055, FM-016→FM-057, FM-018→FM-039, FM-028→FM-048, FM-029→FM-038.

Sólo semántico, **no** detectable por texto (similitud 0.56): FM-010→FM-046
("Desgaste del sello mecánico" → "Fuga por sello mecánico / empaquetadura").

Sucesor ambiguo, **requiere decisión humana**: FM-024 → alguno de FM-051 /
FM-054 / FM-059.

Advertencia para quien escriba la spec de migración: el sucesor **no siempre
es mejor**. Al menos cuatro pares degradaron el código ISO 14224 respecto del
original (FM-004 `ERO`→`HIO`, FM-017 `LOO`→`STP`, FM-024 `PDE`→`NOI`,
FM-022 cambió a una falla funcional peor). Una regla "conservar el ID mayor"
es sistemáticamente perjudicial en esos casos.

Los 8 huérfanos sin sucesor están listados en Pre-requisitos.
