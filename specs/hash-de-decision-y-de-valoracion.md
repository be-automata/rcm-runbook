# Separar el hash de la decisión del hash de la valoración

> AUTOSUFICIENTE: ejecutable en una sesión nueva, por alguien que no
> participó de la conversación que la originó.
>
> Spec corta de bugfix caro de revertir, en la forma que pide
> `.claude/rules/specs.md`: alcance, qué NO cambia, y criterios de
> invariancia. Sin fase de preguntas: no hay comportamiento nuevo que
> descubrir, hay una fórmula mal recortada.

## 1. Alcance

Un único hash, `failure_mode_snapshot`, sella dos artefactos con conjuntos de
insumos distintos: la **valoración** (S/O/D) y la **decisión** RCM. Incluye los
controles, que son insumo de la primera y **no lo son** de la segunda. El
resultado, medido sobre la sesión real: **31 de 32 decisiones marcadas como
desactualizadas por un dato que no las afecta**, y un bloqueador que el agente
no puede resolver por el camino que el propio mensaje le indica.

Esta spec parte el hash en dos y arregla, de paso, el reporte que duplica esos
31 en 62.

### Evidencia

Reproducido de forma independiente sobre `tests/fixtures/uat_sesion_real.json`:

```
decisiones cuyo hash se reproduce quitando UN control: 31 | no reproducen: 0
scores con hash desfasado: 0 de 60
stale_decisions(): 31
¿decision_logic menciona Control?: False
```

Es decir: en el momento de decidir, cada uno de esos 31 modos tenía **un
control menos** del que tiene ahora, y todo lo demás era idéntico. 30 tenían
cero controles y hoy tienen uno; `FM-014` tenía uno y hoy tiene dos.

`failure_mode_snapshot` incluye los controles (`domain.py:297`) con esta
justificación en su docstring (`domain.py:282-283`): *«the current controls
(they justify the Detection rating)»*. **La justificación es correcta para
`RiskScore` y no aplica a `DecisionResult`**: `engine/decision_logic.py` no lee
`Control` en ninguna línea, y `decide(fm, effect, answers)` (`tools.py:638`) no
los recibe.

De ahí el defecto en una frase: **añadir un control no puede cambiar la
política de mantenimiento, pero invalida la decisión que la contiene.**

### Por qué importa más de lo que parece

- **El bloqueador es irresoluble por su propio camino.** Re-ejecutar
  `run_decision_logic` con el mismo cuestionario da la misma política y sólo
  vuelve a sellar el hash. Un bloqueador que no se resuelve haciendo lo que
  pide enseña a ignorar los bloqueadores.
- **Pide firmas humanas sin motivo.** 4 de las 31 decisiones tienen consecuencia
  de seguridad o ambiente y `hitl_confirmed_by` firmado. Recalcularlas exige el
  `approver` otra vez (`tools.py:632-635`): cuatro firmas de auditoría JA1011
  pedidas de nuevo para arreglar un desfase causado por un dato que no entra en
  esa decisión.
- **El reporte los duplica.** `stale_decisions()` (`session.py:549-559`)
  devuelve la **unión** de modos con valoración y/o decisión obsoleta, sin
  distinguir cuál. `compliance.py:102-106` y `:131-135` la consumen las dos y
  etiquetan la misma lista de dos maneras. De los 121 bloqueadores de la sesión,
  **31 son valoraciones fantasma**: los scores están frescos, 0 de 60
  desfasados. Los bloqueadores reales son 90.
- **Contamina el digest.** `session.py:605-607` le repite al modelo, en cada
  turno, una lista de 31 modos que no puede arreglar.

### Entra

- Partir `failure_mode_snapshot` en dos funciones con los insumos de su
  artefacto: la de valoración conserva los controles, la de decisión no.
- Partir `stale_decisions()` en `stale_scores()` y `stale_decisions()`, y que
  cada compuerta consuma la suya.
- Re-sellar los `input_hash` de las 32 decisiones existentes bajo la fórmula
  nueva.

### NO entra — qué NO cambia

- **Ninguna política de mantenimiento.** Esta spec no re-decide nada: cambia
  qué se sella, no qué se concluye.
- **Ninguna firma HITL.** Las 4 confirmaciones de seguridad/ambiente se
  conservan tal cual; el re-sellado no vuelve a pedirlas.
- **La valoración sigue invalidándose con un control nuevo**, que es correcto:
  un control cambia la Detección y alguien debe re-juzgarla.
- La supersesión de modos duplicados, que va en
  [`supersesion-de-modos-de-falla.md`](supersesion-de-modos-de-falla.md). Esta
  spec es independiente y **debería ir primero**: sin ella, aquella migración
  trabaja sobre un estado que miente sobre qué está obsoleto.

## Criterios de invariancia — qué tiene que seguir siendo verdad después

1. **Ninguna política cambia.** Para los 32 modos con decisión, `policy`,
   `consequence_class`, `evident_route`, `hidden_route`, `ffi_hours` y
   `recommended_interval` son idénticos antes y después. Comprobable con un
   diff del estado.
2. **Ninguna firma se pierde ni se vuelve a pedir.** `hitl_confirmed_by` y el
   `hitl_ledger` quedan intactos; los 4 modos firmados siguen firmados.
3. **Las valoraciones siguen protegidas.** Añadir un control a un modo con
   `RiskScore` lo marca como valoración obsoleta. Test explícito: es la
   propiedad que el hash original sí protegía y que no se puede perder al
   partirlo.
4. **Las decisiones dejan de ser sensibles a los controles.** Añadir un control
   a un modo con decisión **no** la marca obsoleta. Test explícito.
5. **Las decisiones siguen siendo sensibles a lo que sí las alimenta.**
   Cambiar el efecto, el patrón de falla, el P-F o la credibilidad **sí** marca
   la decisión obsoleta. Test explícito, uno por insumo: partir un hash es
   fácil de hacer de más y dejarlo insensible a todo.
5b. **Y dejan de serlo a lo que no.** Cambiar `description`, `mechanism`,
   `iso_code`, `cause`, `root_cause`, `tpef` o `weibull_beta` **no** marca la
   decisión obsoleta, y **sí** marca la valoración. Los dos tests van en pareja:
   sale de un sello, no de los dos. (Segunda vuelta; ver la sección de abajo.)
5c. **La tolerancia no se traga un cambio real.** Con controles presentes en el
   modo, un cambio de efecto o de P-F sigue marcando la decisión obsoleta pese a
   la aceptación de sellos heredados. Es el riesgo propio de esa aceptación y
   necesita su test.
6. **Los bloqueadores fantasma desaparecen y no se llevan ninguno real por
   delante.** Sobre el fixture: de 121 se baja a 90, y los 90 restantes son
   exactamente los que había menos los 31 de «valoración desactualizada».

   > CORREGIDO AL IMPLEMENTAR (medido, no estimado). El 90 es el número de la
   > mitad de reporte sola —partir `stale_decisions()` sin tocar la fórmula del
   > hash—, y no corresponde a ningún estado alcanzable de la feature completa.
   > Con las dos mitades aplicadas los números reales son:
   >
   > - fórmula nueva, estado sin re-sellar: **91**. Los 31 de valoración se van;
   >   los de decisión pasan de 31 a 32 porque la fórmula cambió y `FM-019`
   >   —cuyo sello viejo sí llevaba su control— también queda desfasada. Es el
   >   mismo motivo por el que el re-sellado es para las 32.
   > - fórmula nueva + re-sellado: **59**, que es el estado final de esta spec, y
   >   son exactamente los 121 menos los 31 de valoración y los 31 de decisión.
   >   Cuadra con el 42 simulado para «esta spec + la supersesión de los 20
   >   duplicados» (59 − 17) y con la enumeración de esos 42, en la que no hay
   >   ningún bloqueador de «desactualizada».
   >
   > Verificado en `tests/unit/test_resellar_decisiones.py` con los 121 de
   > partida congelados en `tests/fixtures/bloqueadores_uat_antes.txt`: la
   > igualdad se comprueba como conjuntos, no por conteo.
   >
   > SEGUNDA VUELTA: el 91 también quedó superado. Con la aceptación de sellos
   > heredados, el estado **sin migrar** da ya **59** — los mismos que el
   > migrado. Ése es el número que hay que esperar el día del despliegue, y por
   > eso la ventana de degradación dejó de existir.
7. **Cada mensaje dice la verdad.** Un modo con valoración obsoleta produce el
   mensaje de valoración; uno con decisión obsoleta, el de decisión; ninguno
   produce los dos salvo que las dos lo estén.
8. **Idempotencia.** Correr el re-sellado dos veces no cambia nada la segunda.

## Notas de arquitectura

**El principio, en una frase: un hash cubre los insumos de su artefacto.** Hoy
hay un hash para dos artefactos con conjuntos de entrada distintos, y el
resultado es un falso positivo del 97 % (31 de 32).

**Cómo evitar romper la protección al partir.** El riesgo de esta clase de
cambio es recortar de más y dejar el hash de decisión insensible a algo que sí
lo alimenta. Por eso los criterios 4 y 5 van en pareja: uno comprueba lo que
debe dejar de importar, el otro enumera lo que debe seguir importando. El
insumo real de `decide()` es la firma de `decision_logic.decide(fm, effect,
answers)` — lo que no entra ahí, no entra en el hash.

**El re-sellado es migración de datos, no de esquema.** No cambia la forma de
`DecisionResult`, sólo recalcula un campo. Va con el patrón de
`scripts/mutar.py`: volcar el estado previo, aplicar, **releer y comparar**.
Su cabecera documenta por qué —*«un `str.replace` que no encuentra su texto no
avisa: devuelve el original»*—: un script de transformación que no verifica lo
que aplicó miente sobre su resultado.

**`FM-019` obliga a re-sellar aunque no esté obsoleto hoy.** Es la única
decisión fresca, y su hash **sí** incluía su control. Al cambiar la fórmula
quedaría desfasada si no se re-sella. O sea que el re-sellado no es opcional
para «los 31»: es para las 32.

**Lo que esta spec NO desbloquea, con el número.** Simulado: con esta spec
**más** la supersesión de los 20 duplicados, los bloqueadores pasan de 121 a
**42**. Los 42 restantes son, en su mayoría, trabajo de análisis RCM que nadie
hizo: 24 modos decididos sin acción recomendada, 8 huérfanos esperando
decisión, 4 con política pero sin tarea, 3 fallas funcionales que se quedan sin
modos vivos, 2 de intervalo de búsqueda mayor que su FFI, 1 de fuente de TPEF.
**Ninguna cantidad de arquitectura los resuelve**; hacen falta turnos de
conversación con el interesado. Conviene decirlo antes de empezar y no cuando
se descubra que la sesión sigue sin poder exportar.

## Tareas

1. [x] Partir `failure_mode_snapshot` (`domain.py:276-298`) en dos funciones, y
       dejar escrito **en el propio código** por qué los controles entran en una
       y no en la otra. Sin ese comentario, el próximo que toque la lista los
       vuelve a meter «por completitud».
       → `score_snapshot` y `decision_snapshot` (`domain.py:316-340`, insumo común en `domain.py:276-296`), con el
       insumo común factorizado en `_insumos_del_modo` y el porqué escrito en el
       bloque de comentario que las separa.
2. [x] Partir `stale_decisions()` (`session.py:549-559`) en `stale_scores()` y
       `stale_decisions()`; ajustar `compliance.py:102-106` y `:131-135` para
       que cada una consuma la suya, y `digest_es` (`session.py:605-607`).
       → `session.py:547-578`; P4 consume `stale_scores()` (`compliance.py:104`),
       P5 `stale_decisions()` (`compliance.py:134`), y el digest emite los dos
       avisos por separado (`session.py:626-633`).
3. [x] Tests de los criterios 3, 4 y 5 — la pareja «deja de importar» / «sigue
       importando», con un caso por insumo.
       → `tests/unit/test_hash_decision_vs_valoracion.py` (22 tests; el 7
       también queda cubierto).
4. [x] Script de re-sellado de las 32 decisiones, estilo `scripts/mutar.py`,
       con volcado previo y relectura.
       → `scripts/resellar_decisiones.py`, probado en
       `tests/unit/test_resellar_decisiones.py` (incluidas sus comprobaciones
       contra un resultado adulterado a mano).
5. [x] Verificar el criterio 6 sobre el fixture: 121 → 90, y que los 90 son los
       mismos menos los 31 de valoración.
       → medido: 121 → 91 sin re-sellar y → 59 re-sellado. Ver la corrección
       bajo el criterio 6.
5b.[x] **Segunda vuelta — estrechar el sello a lo que `decide()` lee.** Sacar de
       `decision_snapshot` los siete campos descriptivos; siguen en la
       valoración.
       → `_insumos_de_la_decision` (`domain.py`), con la contrapartida asumida
       escrita al lado. Tests en pareja en
       `tests/unit/test_hash_decision_vs_valoracion.py`
       (`TestLosCamposDescriptivosNoEnsucianLaDecision`).
5c.[x] **Segunda vuelta — aceptar sellos heredados por prefijo de controles**,
       para que desplegar no degrade el estado vivo.
       → `sello_de_decision_heredado` (`domain.py`) y
       `_sellos_de_decision_validos` (`session.py`), consumido por
       `stale_decisions()`. La verificación de `resellar_decisiones.py` pasa a
       estricta por la misma razón.
6. [x] `spec-verifier` antes del PR (`.claude/rules/specs.md:22`) y
       `production-validator` en local.
       → `spec-verifier`: CUMPLE los 8 criterios, con línea base independiente
       (ejecutó el código de `3433622` sobre el fixture y obtuvo los mismos 121
       de `bloqueadores_uat_antes.txt`). `production-validator`: apto con
       reservas, todas del script de migración; las cuatro se corrigieron —
       guarda de sellos huérfanos (`session.py:559-586`), volcado que ahora es
       una copia entera y restaurable que no se pisa, escritura atómica, y
       código de salida 2 sin escribir nada cuando el estado no valida.

## Segunda vuelta: el sello sellaba de más, y la ventana de despliegue

Una investigación posterior sobre los dos agujeros que esta sección declaraba
abiertos encontró que el primero era mucho mayor de lo descrito y el segundo
mucho menor. Ambos resueltos o cerrados; queda una interacción que hay que
conocer antes de desplegar.

### El sello de la decisión incluía siete campos que `decide()` no lee

No era sólo `tpef`. Enumerado contra el código: de `fm`, `decide()` toca
`failure_pattern`, `credible`, `pf_interval_hours` y `weibull_eta_hours` — más
`id` y `non_credible_discard`, que sólo entran en el texto de un error. El sello
llevaba **once** campos. Los siete de más —`description`, `mechanism`,
`iso_code`, `cause`, `root_cause`, `tpef`, `weibull_beta`— no pueden cambiar la
política.

El daño es el mismo que motivó esta spec, por otra puerta: **corregir una errata
en una descripción marcaba la decisión como obsoleta**, y en los cuatro modos con
firma JA1011 eso vuelve a pedir la firma. Durante el UAT el interesado corrigió
descripciones de modos repetidamente.

**Decidido: el sello se estrecha a los cuatro campos reales** (más el efecto
entero, que `classify_consequence` recorre). La contrapartida asumida es que
reescribir una descripción hasta convertir el modo en otro distinto ya no
invalida su decisión: el sello es «los insumos de la conclusión», no «la
identidad del modo». Si alguna vez hace falta lo segundo, es otro mecanismo y
otro nombre. Los siete siguen sellados en la **valoración**, que es donde
pertenecen.

Se descartó dejarlo como estaba y limitarse a corregir el docstring: convive con
falsos positivos que ya cuestan firmas humanas, que es exactamente lo que esta
spec vino a eliminar.

### `answers` no es un agujero alcanzable

Es cierto que cambiar una respuesta del cuestionario cambia la política —medido:
`MBT` frente a `OHF`— y que no está en ningún sello. Pero **no puede derivar**:
`run_decision_logic` (`tools.py:600-660`) es el único camino de escritura,
siempre re-ejecuta `decide()` y vuelve a sellar, y las answers no se almacenan
en ninguna parte. No existe un estado donde la decisión guardada contradiga unas
respuestas guardadas, porque no hay respuestas guardadas.

Lo que sí hay es un hueco de **procedencia**, y es parcial: `justification`
registra qué rama de la cascada disparó — 7 justificaciones distintas sobre 32
decisiones, del tipo *«Patrón de fin de vida útil con restauración/sustitución
programada viable»*, que implica `aging_related` y `restoration_feasible`. Es un
registro con pérdida, no una ausencia. Persistir las answers cerraría la
reproducibilidad JA1011 del todo, pero es un cambio de modelo y va aparte.

### La ventana de despliegue ya no existe

Esta sección decía que desplegar sin migrar dejaba la sesión **peor** que antes
(32 desfasadas en vez de 31). Ya no.

Un sello guardado con una fórmula anterior se reconoce **reconstruyéndolo**. Los
controles son *append-only* —`RCMSession.add_control` (`session.py:415-429`)
sólo hace `append`, y no hay ninguna ruta de borrado ni de edición en el repo—,
así que la lista de controles de cualquier instante pasado es necesariamente un
**prefijo** de la actual. Enumerar prefijos no es una heurística: es enumerar la
historia completa. Sobre la sesión de UAT reconstruye **32 de 32**, con 3
candidatos por modo como máximo.

De ahí la propiedad que elimina la ventana, y es una demostración y no una
medición: el conjunto aceptado incluye `controls[:len(controls)]`, que **es** la
fórmula anterior. Los sellos que la app nueva acepta son un superconjunto de los
que aceptaba la vieja, luego **ninguna decisión fresca hoy puede quedar obsoleta
al desplegar**. Medido de todos modos: el estado sin migrar da ya los mismos
**59** bloqueadores que el migrado.

Dos decisiones de dónde vive esa tolerancia:

- **En la comparación, no en `decision_snapshot`.** El sello canónico no puede
  tener variantes o deja de haber uno.
- **En la sesión, no en el cargador.** Así la heredan las dos rutas de lectura —
  el chat (`tools._load`) y la descarga (`app._sesion_guardada`)— sin que
  ninguna se quede con el criterio viejo.

Y la verificación del guion de re-sellado pasa a ser **estricta**: usaba
`stale_decisions()`, que ahora es tolerante, así que habría dado por bueno un
fichero en el que no aplicó nada. Normalizar al sello canónico es justamente su
trabajo.

Se descartaron: migrar antes de desplegar (invierte la ventana y la agrava —
bajo la fórmula vieja un estado re-sellado da 32 desfasadas, alcanza a los
cuatro modos firmados y dispara `HITLRequired`); la aceptación dual ingenua
(rescata 1 de 32); y el re-sellado perezoso al escribir en `_load`, que sin el
criterio de reconocimiento no tiene definición y además destruye el sello viejo,
cerrando la puerta a revertir el código.

### La interacción que hay que conocer antes de desplegar

Las dos correcciones se combinan de una forma que conviene tener presente:
**una decisión que todavía lleva sello heredado conserva la sensibilidad
vieja.** Medido: sobre el estado sin migrar, una errata en la descripción sí
marca la decisión obsoleta; sobre el estado ya normalizado, no.

Consecuencia práctica: la migración de Neon **deja de ser urgente** —no hay
ventana de degradación, y se puede correr cuando convenga, con el interesado
desconectado— pero **sigue siendo necesaria** para que el arreglo del falso
positivo llegue a la sesión real. Alternativa válida si se prefiere no tocar
Neon nunca: se normaliza sola, porque cualquier `run_decision_logic` futuro
reescribe el sello con la fórmula nueva.

`SCHEMA_VERSION` se queda en 1 en todos los pasos: no cambia la forma de nada, y
subirlo activaría el guardián de `tools.py:96-101` contra uno mismo si hiciera
falta revertir el contenedor.

### Retirada de la compatibilidad

El código de aceptación es temporal y lleva su condición de retirada escrita al
lado: **borrable cuando `stale_decisions()` de la sesión viva sea `[]` con la
aceptación desactivada.** Depende del invariante *append-only*; si alguien añade
borrado o edición de controles, deja de ser exhaustivo y hay que volver a la
migración. Comprobado que la spec de supersesión no lo rompe: es un libro que
conserva los modos y no toca ni los sellos ni los controles.

## Supuestos

- SUPUESTO: la secuencia que lo produjo fue «decidir sin controles → una
  compuerta reclama controles → rellenarlos en bloque → la compuerta pasa a
  quejarse de decisiones obsoletas». Encaja con que los scores estén frescos
  (se registraron después) y con que seis controles se titulen literalmente
  *«Sin control actual registrado — …»*. **No es verificable**: el estado
  guardado no tiene marcas de tiempo por turno. Lo que sí está verificado es el
  estado en cada instante de cálculo. La causa del defecto no depende de esta
  reconstrucción.
- SUPUESTO: ningún consumidor externo depende de que `failure_mode_snapshot`
  siga existiendo con ese nombre y esa firma. Es interno al paquete; conviene
  comprobarlo con `grep` antes de renombrar.
