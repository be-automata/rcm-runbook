# Supersesión de modos de falla y limpieza de la sesión de UAT

> AUTOSUFICIENTE: ejecutable en una sesión nueva, por alguien que no
> participó de la conversación que la originó.

## 1. Alcance

En la sesión de UAT del 09–11 ago 2026 el interesado reestructuró el análisis a
media sesión —dividió y renombró fallas funcionales— y el agente re-registró
los modos desde `FM-033` sin descartar los viejos. Quedaron **28 modos creíbles
huérfanos** que contaminan el entregable y bloquean la exportación definitiva.

Esta feature da al sistema la noción que le falta —*este modo fue sustituido
por aquel*— para que la reestructuración sea expresable, y limpia la sesión
existente. Sin ella el problema se repite en cada análisis que cambie de
estructura, que es lo normal en RCM.

Su antecedente es [`trazabilidad-y-clasificacion-en-el-excel.md`](trazabilidad-y-clasificacion-en-el-excel.md),
que hizo que esos 28 modos **se vean** en el entregable en vez de desaparecer
en silencio. Aquella spec decidió deliberadamente no ocultarlos ni descartarlos:
mostrar el estado real era su trabajo, corregirlo es el de ésta.

### Entra

- Un modo de falla puede declararse **sustituido por otro**, con motivo, sin
  perder el registro.
- Las herramientas que hacían inexpresable la reestructuración: renombrar una
  falla funcional, y detectar un modo casi duplicado dentro de la misma falla.
- Un flujo de resolución **con humano en el bucle**: el sistema propone
  candidatos, una persona los aprueba o los arbitra.
- La migración de la sesión de UAT (`demo-7aa88eb4-0889-4a91-b7b5-6a5cd4a3edc9`),
  única con datos reales.
- Que un modo sustituido salga de las compuertas de exportación y del AMEF, y
  quede en la hoja de auditoría con su sucesor.

### NO entra (explícito)

- **Fusionar modos automáticamente.** Ver Notas de arquitectura: la detección
  se automatiza, la resolución no. El repo ya fijó este principio en
  `session.py:235-246`.
- Cambiar la forma del entregable más allá de la sección de supersesiones en
  AUDITORIA RCM. Los encabezados siguen congelados; `AMEFRow`/`PlanRow` no
  ganan campos.
- **Las 31 decisiones desactualizadas.** Diagnosticadas y con spec propia:
  [`hash-de-decision-y-de-valoracion.md`](hash-de-decision-y-de-valoracion.md).
  Resumen: un solo hash sella dos artefactos con insumos distintos, e incluye
  los controles, que no alimentan la decisión. Añadir un control invalidó 31
  decisiones que no pudo cambiar. **Esa spec debería ir primero**: sin ella,
  la migración de acá trabaja sobre un estado que miente sobre qué está
  obsoleto. Y de paso, las «31 valoraciones desactualizadas» que se creían
  parte del problema **no existen**: 0 de 60 scores tienen el hash desfasado;
  son un defecto de reporte. Los bloqueadores reales son 90, no 121.
- Detección semántica por embeddings. El criterio textual medido abajo tiene
  95 % de exhaustividad; el 5 % que se pierde lo resuelve un humano mirando la
  lista.

## Pre-requisitos

- **Causa raíz, verificada en el código.** Tres huecos, y el que se suele
  suponer no es el culpable:

  1. `add_failure_mode` **sí** acepta `reemplazar=True` (`tools.py:413`), pero
     su deduplicador está acotado a la **misma** falla funcional
     (`session.py:346-348`: `if existing.functional_failure_id != functional_failure_id: continue`).
     Como los modos nuevos se registraron bajo FF **nuevas**, el bucle nunca
     miró los viejos. Y si el agente hubiera pasado `reemplazar=True` habría
     recibido una excepción, no una fusión (`session.py:384-395`). **El arreglo
     de prompt que parece obvio es inejecutable.**
  2. `add_functional_failure` (`session.py:327-337`) **no tiene** parámetro
     `reemplazar` ni ninguna forma de renombrar. El interesado «renombró» FF y
     lo único que el agente podía hacer era crear nuevas. Ésta es la grieta
     raíz.
  3. `add_failure_mode` compara con `_same_text` (`session.py:349`), que es
     igualdad exacta normalizada. El comparador near-duplicate `_casi_igual`
     **ya existe** (`session.py:235`) y se usa en `add_task`. Por esa puerta
     entró `FM-036`/`FM-040` («Obstrucción parcial del impulsor» /
     «Impulsor parcialmente obstruido»), **misma FF**, mismo ISO, misma
     política.

- **Estado a migrar, medido.** Sesión `demo-7aa88eb4-0889-4a91-b7b5-6a5cd4a3edc9`,
  en Neon: esquema `ai`, tabla `agno_sessions`, campo
  `session_data -> session_state -> rcm`. `DATABASE_URL` está en `.env.deploy`
  (usar `postgresql://`; el valor guardado trae el prefijo
  `postgresql+psycopg://`, que `psycopg.connect` no acepta). **Hay una copia
  congelada y anonimizada en `tests/fixtures/uat_sesion_real.json`**, que es la
  que deben usar los tests.

  | | |
  |---|---|
  | Modos | 63 (60 creíbles, 3 descartados por no credibilidad) |
  | Modos creíbles sin decisión | 28, **todos** en `FM-001..FM-032` |
  | Duplicados con sucesor | 20 (ver Anexo) |
  | Huérfanos sin reemplazo | 8 (ver Anexo) |
  | Decisiones | 32, de las cuales 31 desactualizadas |

- **Las otras cuatro sesiones de la base están vacías** (fase 1, 0 modos). El
  radio de impacto de la migración es **una fila**.

- **No hay migraciones de esquema.** `SCHEMA_VERSION = 1`
  (`session.py:32`) y nunca subió. Añadir un campo opcional al modelo no la
  obliga a subir, pero conviene decidirlo explícitamente al implementar.

## 3. Criterios de aceptación

Delivery a enterprise-grade product (executed, observed, and verified),
leverage on `.claude/agents/testing/production-validator.md` to run old and new UAT/Test cases in the local and target (remote) environment.

1. **La supersesión es expresable y no destruye nada.** Un modo puede quedar
   marcado como sustituido por otro, con motivo, conservando su registro
   completo. `credible` **no** se usa para esto: `non_credible_discard` es el
   campo de auditoría JA1011 para incredibilidad técnica, y usarlo como
   papelera de deduplicación corrompe la semántica del entregable.
2. **La reestructuración deja de ser inexpresable.** Existe forma de renombrar
   una falla funcional sin crear una nueva, y `add_failure_mode` detecta el
   casi duplicado dentro de la misma falla funcional. Un test reproduce la
   secuencia de la sesión de UAT y comprueba que ya no genera un rango
   huérfano.
3. **La detección propone; el humano resuelve.** Ninguna supersesión se aplica
   sin confirmación humana explícita, registrada en el `hitl_ledger` — el mismo
   mecanismo que `compliance.py` ya exige para consecuencias de seguridad y
   ambiente. Un test demuestra que no existe camino automático.
4. **El criterio de detección se comporta como está medido.** Sobre
   `tests/fixtures/uat_sesion_real.json`: 19 candidatos propuestos, **0 falsos
   positivos**, los **8 huérfanos no propuestos**, y los 3 pares legítimos de
   `FM-051`/`FM-054`/`FM-059` **no** propuestos. Si el criterio se cambia, este
   test dice cuánto se degradó.
5. **La sesión de UAT queda migrada y verificable.** Tras la migración: los 20
   duplicados enlazados a su sucesor, los 8 huérfanos **intactos y aún
   bloqueando** la exportación, y una copia de seguridad del estado previo. El
   AMEF pasa de 60 filas a 40, y las 8 pendientes quedan visibles, no ocultas.
6. **El entregable declara las supersesiones.** La hoja AUDITORIA RCM lista
   cada modo sustituido con su sucesor y el motivo, con el `FM-id` en celda
   propia. Los sustituidos no aparecen en AMEF ni en PLAN.
7. **Sin regresión.** `tests/export/test_golden.py` pasa sin modificar; la
   compuerta sigue rechazando lo que rechazaba; y las sesiones existentes
   cargan sin error (`RCMSession.model_validate` sobre el fixture y sobre las
   cuatro sesiones vacías).

## 4. Notas de arquitectura

**Automatizar la detección, nunca la resolución.** El repo ya fijó este
principio y conviene citarlo porque es la decisión de diseño central. El
docstring de `_casi_igual` (`session.py:235-246`) dice: *«No se fusionan solas:
fusionar a ciegas borraría una tarea legítima distinta. Quien llama decide, y
aquí solo se responde a la pregunta.»* Lo mismo vale un nivel más arriba, y las
mediciones lo respaldan:

- **Precisión de detección: 19/19 (100 %).** Ningún par propuesto es un modo
  legítimo distinto.
- **Precisión de resolución: 15/19 (79 %).** En **4 pares el sucesor es peor
  que el original** (ver Anexo). Una regla «conservar el ID mayor» degradaría
  el entregable en esos cuatro.
- **Exhaustividad: 19/20 (95 %).** Se pierde `FM-010 → FM-046` («Desgaste del
  sello mecánico» → «Fuga por sello mecánico»), similitud 0.56: invisible para
  cualquier umbral textual utilizable.

**El criterio de detección, y por qué el filtro importa más que el umbral.**

> Candidato = par (A, B) donde A es creíble y **sin** decisión, B es creíble y
> **con** decisión, `ratio(normalizar(A.desc), normalizar(B.desc)) ≥ 0.85`, y B
> se registró después de A. Normalizar = minúsculas, sin acentos, sin
> puntuación, espacios colapsados.

La restricción «uno sin decisión, otro con decisión» es la que da el 100 % de
precisión. Sin ella, el mismo umbral aplicado simétricamente marca además los
tres pares `FM-051`/`FM-054`/`FM-059` —«Holguras internas incorrectas» sobre
FF-017, FF-014 y FF-012, con políticas distintas (MBT / MBC / ReP)— y la
precisión cae a 86 %. **Esos tres son RCM legítimo**: un mismo modo físico
causa varias fallas funcionales y debe registrarse en cada una. Bajar el umbral
a 0.72 no recupera `FM-010` (0.56) y sí empieza a emparejar cosas absurdas.
**0.85 es el óptimo local sobre estos datos.**

**DECIDIDO — libro de supersesiones, no campo en `FailureMode`.** Con
`sustituido_por(fmid)` y `sustituidos()` como métodos derivados del libro, no
como estado duplicado; así el consumo en `rows.py` y `compliance.py` cuesta lo
mismo con las dos formas y deja de ser un criterio.

Primero, un hecho que despeja la mitad del debate: **ninguna de las dos opciones
toca los hashes.** El sello enumera sus campos uno por uno, así que un campo
nuevo no entra en el digest salvo que alguien lo añada a esa lista. El argumento
«un campo invalida las 92 valoraciones y decisiones» es falso. Pero **hay que
escribir en el propio sello por qué la supersesión queda fuera** —no es un
insumo de la decisión, es un hecho sobre el análisis—: sin ese comentario, el
próximo que añada un campo lo mete «por completitud» y detona todo.

> ACTUALIZADO. `failure_mode_snapshot` ya no existe: se partió en
> `score_snapshot` (con controles) y `decision_snapshot` (sin) —ver
> [`hash-de-decision-y-de-valoracion.md`](hash-de-decision-y-de-valoracion.md)—.
> Los campos comunes viven en `_insumos_del_modo` (`domain.py:276-296`), que es
> donde va ese comentario, junto al que ya explica por qué los controles entran
> en un sello y no en el otro.

Descartado ese factor, lo que decide es **deshacer**. Un campo que se pone a
`None` para revertir **borra el hecho de que la supersesión ocurrió**, y eso
viola el principio que el propio dominio ya fijó (`domain.py:8`: *«Non-credible
failure modes carry a documented discard (kept, never deleted)»*). Y deshacer
no es un caso raro acá: hay **4 pares donde el sucesor es peor que el
original** (Anexo). El libro además da su sitio natural a quién aprobó, cuándo
y por qué, mantiene una sola fuente con el `hitl_ledger` del criterio 3, y
tiene precedente en el repo (`session.py:145`).

**Tres cosas que hay que resolver y que ninguna versión de esta spec veía:**

1. **Tres fallas funcionales se quedan sin modos vivos.** Verificado: excluidos
   los 20 sustituidos, `FF-005`, `FF-006` y `FF-008` no conservan ninguno, y
   `compliance.py:81-84` bloquea toda FF sin modos → **3 bloqueadores nuevos**.
   Decisión a tomar explícitamente: `compliance.py:81` debe seguir contando los
   sustituidos —una FF cuyo modo fue sustituido por otro colgado de otra FF
   sigue analizada— **o** la migración debe reasignar esas FF. Recomendado lo
   primero, y que AUDITORIA lo declare.
2. **La cadena.** Nada impide `A → B` y luego `B → C`. Los consumidores
   necesitan el sucesor **final**, no el inmediato, y el libro debe rechazar
   ciclos. Con un campo esto se olvida; con el libro es una función con test.
3. **`_next_id` cuenta el diccionario** (`session.py:151-152`:
   `len(existing) + 1`). Cualquier implementación que **borre** los sustituidos
   en vez de marcarlos **reutiliza IDs ya emitidos** y corrompe la auditoría.
   Otro argumento por el no-borrado, y merece test de regresión.

**DECIDIDO — `SCHEMA_VERSION` sube a 2.** El guardián existe y hace una sola
cosa (`tools.py:96-101`): rechaza cargar una sesión cuya versión sea mayor que
la de la aplicación. Es un guardián de **rollback de la aplicación**, no de
migración. El escenario que protege es real acá: pydantic v2 ignora los campos
desconocidos, así que una versión anterior cargaría una sesión con
supersesiones, **las descartaría en silencio**, y al siguiente `_save`
sobrescribiría la fila de Neon sin ellas. Pérdida irreversible, sin error, en
la única sesión con datos reales.

El criterio es la **asimetría**: subir cuesta una línea y dos tests que ya hay
que tocar (`tests/unit/test_models.py:229` y `tests/unit/test_app.py:187`
afirman `== 1`); no subir cuesta, en el peor caso, la sesión que esta spec
existe para rescatar. Cuando un lado del error es un rato de trabajo y el otro
es el dato del interesado en silencio, no se ponderan probabilidades.

Y con el cambio va **escrita en `session.py:32` la regla de cuándo se sube**:
*se sube cuando un campo nuevo carga información que una versión anterior
perdería al reescribir*. Sin esa frase el 2 es tan arbitrario como el 1 y la
próxima decisión se vuelve a discutir desde cero.

**Por qué no basta con arreglar el modelo.** Los 28 huérfanos ya existen en
producción y bloquean la exportación definitiva del interesado. Arreglar
`add_functional_failure` evita el próximo caso pero no rescata éste; migrar sin
arreglar el modelo garantiza que vuelva a pasar. Van juntos, y en este orden:
modelo y herramientas primero, migración después, porque la migración usa la
herramienta nueva y así queda ejercitada por el propio uso.

**La contaminación no se limita a los 28.** Hay duplicados **entre los 32
decididos**, que hoy se imprimen en el plan:

- `FM-019` / `FM-033` / `FM-034` — los tres «Restricción u obstrucción en la
  aspiración», los tres MBT, ruta B: **tres filas idénticas** en el AMEF.
  Además `FM-033` cuelga de FF-007 («La bomba contamina el agua potable»), un
  emparejamiento sin sentido físico.
- `FM-005` / `FM-037` — «Bajo nivel en el depósito de aspiración», ambos MBC,
  con **clasificación de consecuencia contradictoria**: `FM-005` ruta **A**
  (seguridad/ambiente, sin tarea) y `FM-037` ruta **B** (operacional, con dos
  tareas). El mismo modo físico, dos consecuencias distintas, en el mismo
  entregable.
- `FM-036` / `FM-040` — misma FF, mismo ISO, misma política, tareas casi
  idénticas.

Estos **no** los detecta el criterio de arriba, porque ambos miembros tienen
decisión. Entran por el arbitraje humano de la tarea 5, y hay que listarlos
aparte para que no se pasen.

**Copia de seguridad antes de migrar.** `scripts/mutar.py` es el precedente de
script de mantenimiento del repo, y su cabecera documenta por qué un script de
transformación que no verifica lo que aplicó miente sobre su resultado: *«Un
`str.replace` que no encuentra su texto no avisa: devuelve el original»*. La
migración debe volcar el estado previo a fichero, aplicar, y **releer y
comparar** antes de dar por buena la escritura.

**Lo que esta spec NO promete, con el número.** Simulado sobre el fixture: con
esta spec **más** la del hash, los bloqueadores pasan de 121 a **42**. Los 42
restantes son en su mayoría trabajo de análisis RCM que nadie hizo — 24 modos
decididos sin acción recomendada, los 8 huérfanos esperando decisión, 4 con
política pero sin tarea, las 3 FF sin modos vivos, 2 de intervalo de búsqueda
mayor que su FFI, 1 de fuente de TPEF. **Ninguna cantidad de arquitectura los
resuelve**: hacen falta turnos de conversación con el interesado. Va escrito
acá para que nadie descubra a mitad de la implementación que la sesión sigue
sin poder exportar el definitivo.

## 5. Tareas

1. [ ] Campo de supersesión en `FailureMode` (`domain.py:87-105`), opcional y
       con motivo. Decidir explícitamente si sube `SCHEMA_VERSION`.
2. [ ] `add_functional_failure` acepta renombrar (`session.py:327-337`), y
       `add_failure_mode` usa `_casi_igual` en vez de `_same_text`
       (`session.py:349`) dentro de la misma falla funcional.
3. [ ] Herramienta de supersesión expuesta al agente, que **exige**
       confirmación humana y la registra en el `hitl_ledger`.
4. [ ] Detector de candidatos con el criterio de las Notas, más su test de
       comportamiento medido (criterio 4).
5. [ ] Script de migración estilo `scripts/mutar.py`: vuelca el estado previo,
       propone los 20 pares del Anexo para aprobación en lote, exige arbitraje
       humano para `FM-024` (sucesor ambiguo), para los 4 pares de ISO
       degradado y para las tres contaminaciones entre modos decididos; aplica;
       relee y compara.
6. [ ] Sección de supersesiones en AUDITORIA RCM, y exclusión de los
       sustituidos en `rows.py` y en `compliance.py`.
7. [ ] Test que reproduce la secuencia de reestructuración de la sesión de UAT
       y comprueba que ya no genera un rango huérfano (criterio 2).
8. [ ] Verificar con `spec-verifier` antes del PR (`.claude/rules/specs.md:22`)
       y con `production-validator` en local y en el entorno desplegado
       (`docs/DESPLIEGUE_CLOUDFLARE_ES.md`; desconectar la VPN antes, o
       `wrangler` no despliega).

## Supuestos

- **DECIDIDO (ya no es supuesto): los 8 huérfanos siguen vivos y bloqueando, y
  el sistema no construye un estado «pendiente de arbitraje» para ellos.** Un
  modo sin supersesión es un modo del análisis: no hay estado nuevo ni código
  nuevo, y el comportamiento observable es el que ya existe — 8 bloqueadores
  con el mensaje *«El modo FM-XXX no tiene decisión RCM»*, que es correcto y
  accionable.

  La alternativa —un tercer estado explícito que los declare en espera— **no
  es neutral: es una postura peor disfrazada de abstención**. Nombrarlos
  «pendientes de arbitraje» le comunica al agente y al interesado que son un
  residuo administrativo de la reestructuración, y no lo son: los 8 tienen
  valoración S/O/D completa —trabajo de análisis ya hecho y correcto—, 14 de
  los 28 tienen consecuencia de seguridad o ambiente, y 8 de las 11 fallas
  ocultas de toda la sesión están en ese conjunto, incluido `FM-031` (válvula
  de aislamiento manual cerrada), el modo canónico por el que una bomba de
  reserva no arranca. Un modo con consecuencia de seguridad, ya valorado, no
  espera arbitraje: espera una decisión RCM, que es lo que el sistema ya dice.

  El criterio general: **el sistema se abstiene sólo cuando el valor por
  defecto sería destructivo.** «Sigue en el análisis y bloquea» es el defecto
  no destructivo, el que preserva el trabajo y fuerza la conversación.

  Lo que sí hay que añadir, y no cuesta nada: que el script de migración
  **imprima los 8 con su ID, descripción y consecuencia** al terminar. Que
  bloqueen garantiza que no se pierdan; listarlos con su riesgo a la vista es
  lo que hace que se atiendan.
- SUPUESTO: el emparejamiento del Anexo es correcto salvo donde se marca lo
  contrario. Se estableció con similitud textual, revisión manual de la falla
  funcional de origen y destino, y comparación del código ISO contra el
  catálogo. **Requiere validación del interesado antes de aplicarse**, no es
  un dato del sistema.
- SUPUESTO: la sesión de UAT sigue en Neon cuando se ejecute esto. Si no, la
  migración pierde su objeto pero el resto de la spec sigue siendo válido, y
  el fixture congelado permite verificarla igual.

## Anexo — los 20 duplicados con sucesor

Pares `viejo → sucesor`, agrupados por el criterio con que se establecieron.

**Descripción normalizada idéntica** (verificado mecánicamente, alta confianza):
`FM-001→FM-035`, `FM-002→FM-036`, `FM-003→FM-052`, `FM-004→FM-043`,
`FM-007→FM-056`, `FM-008→FM-058`, `FM-017→FM-041`, `FM-022→FM-060`,
`FM-023→FM-040`, `FM-027→FM-047`, `FM-030→FM-042`, `FM-032→FM-044`.

**Descripción muy próxima** (similitud ≥ 0.85, revisado a mano):
`FM-009→FM-053`, `FM-011→FM-055`, `FM-016→FM-057`, `FM-018→FM-039`,
`FM-028→FM-048`, `FM-029→FM-038`.

**Sólo semántico, no detectable por texto** (similitud 0.56):
`FM-010→FM-046` — «Desgaste del sello mecánico» → «Fuga por sello mecánico /
empaquetadura».

**Sucesor ambiguo, requiere decisión humana:**
`FM-024` → alguno de `FM-051` / `FM-054` / `FM-059`.

### Advertencia: el sucesor no siempre es mejor

Cuatro pares **degradaron** respecto del original. Una regla «conservar el ID
mayor» es sistemáticamente perjudicial en estos casos:

| Par | Degradación |
|---|---|
| `FM-004→FM-043` | ISO `ERO` → **`HIO`** («Alta salida»). La cavitación no produce salida alta; el código viejo era correcto. |
| `FM-017→FM-041` | ISO `LOO` → **`STP`** («Falla para detenerse»). Una válvula de descarga parcialmente cerrada no es un fallo de parada. |
| `FM-024→FM-051` | ISO `PDE` → **`NOI`** («Ruido»), y colgado de FF-017 («La bomba principal no puede arrancar»). Doblemente mal. |
| `FM-022→FM-060` | Sentido de giro incorrecto pasó de FF-013 («Pérdida de presión en la descarga», correcto) a FF-021 («Protección mecánica»). |

### Los 8 huérfanos, sin sucesor

`FM-006` (degradación del aislamiento del motor), `FM-012` (válvula de
retención bloqueada abierta), `FM-013` (deriva del transmisor de presión o
caudal), `FM-020` (entrada de aire o pérdida parcial de cebado), `FM-021`
(velocidad de giro inferior a la requerida), `FM-025` (fuga importante o bypass
en la descarga), `FM-026` (transmisor de presión o manómetro defectuoso),
`FM-031` (válvula de aislamiento manual cerrada).

**El rango nuevo no es un superconjunto del viejo.** De los 28, **14 tienen
consecuencia de seguridad o ambiente** y **8 de las 11 fallas ocultas de toda
la sesión** están en este conjunto. Descartarlos en bloque borraría análisis
correcto sobre los modos de mayor riesgo.
