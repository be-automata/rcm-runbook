# Glosario y terminología del agente

> AUTOSUFICIENTE: ejecutable en una sesión nueva, por alguien que no
> participó de la conversación que la originó.

## 1. Alcance

El interesado pidió, en el UAT del 09–11 ago 2026, «definir un glosario de
terminología en el contexto del agente» y usar **«fallo» en vez de «falla»**
para el mercado español. Hoy existe `docs/GLOSARIO.md` y el agente **no lo ve
nunca**. Esta feature conecta la terminología al contexto del agente y resuelve
por escrito el conflicto falla/fallo, que no es trivial porque el entregable
del cliente dice «Falla» en encabezados congelados.

Hallazgo 4 de esa ronda. El propio interesado lo calificó de no crítico en su
parte de fuga de inglés; la parte de falla/fallo sí es de producto.

### Entra

- Conectar la terminología al contexto del agente, de forma que aplique
  siempre y no dependa de que el agente decida consultarla.
- Resolver y **dejar escrita** la decisión falla/fallo, con su alcance exacto:
  qué texto cambia y qué texto no puede cambiar.
- Reducir la fuga de términos en inglés cuando existe equivalente en español.
- Reescribir `docs/GLOSARIO.md` para que sirva a los dos públicos que hoy
  confunde: quien programa y el agente.

### NO entra (explícito)

- Cambiar los encabezados del Excel. Están congelados verbatim contra el
  benchmark del cliente y hay dos golden tests que lo blindan
  (`tests/export/test_golden.py:26-30`). Dicen «Falla Funcional», «Modo de
  Falla (ISO 14224)», «Falla Evidente (ABCD)», «Falla Oculta (AEFG)», y
  **seguirán diciéndolo**.
- Renombrar identificadores del código (`FailureMode`, `FunctionalFailure`,
  `failure_mode_id`). Están en inglés y así se quedan; el glosario existe
  precisamente para mapearlos.
- Traducir los mensajes de validación del dominio. Ya están en español y
  tienen su propia lógica probada.
- El defecto conocido de `Quinquenal` en el catálogo de frecuencias
  (`catalogs.py:89-91`: su posición dice quincena y la palabra dice cinco
  años). Es un error de terminología real y adyacente, pero tocarlo cambia un
  valor del MENU del cliente y merece su propia decisión.

## Pre-requisitos

- **El glosario existe y el agente no lo ve. Verificado:**
  - `docs/GLOSARIO.md`, 50 líneas.
  - Única referencia en todo el código: un **docstring de módulo**,
    `src/rcm_runbook/agent/instructions_es.py:1` →
    `"""System prompt del Facilitador RCM (español). Terminología: docs/GLOSARIO.md."""`
    Un docstring no entra en el contexto del modelo.
  - La base de conocimiento carga dos ficheros y ninguno es el glosario:
    `src/rcm_runbook/knowledge/handbook.py:16` →
    `_SOURCES = ("rcm_handbook_com.md", "client_method_20_steps.md")`.

- **Qué es hoy `GLOSARIO.md`, que no es lo que su nombre sugiere.** Es una
  **tabla de correspondencia**: término en español ↔ identificador en el código
  ↔ columna del Excel ↔ herramienta o argumento. Sirve a quien programa. No
  contiene ninguna regla sobre **cómo debe hablar el agente**. Conectarlo tal
  cual no resuelve el pedido: haría que el agente pudiera consultar en qué
  columna cae `root_cause`, que no es lo que se pidió.

- **Medición del problema sobre la sesión real de UAT** (78 turnos,
  154 K caracteres de salida del agente):
  - `falla*`: **411** ocurrencias. `fallo*`: **0**.
  - Fuga de inglés: **18** ocurrencias — `standby` ×11, `P-F interval` ×5,
    `failure finding`, `spare`. Marginal, como dijo el interesado.

- **El conflicto que hay que resolver antes de tocar nada.** El entregable dice
  «Falla» en columnas que no se pueden renombrar, y el cliente del benchmark
  usa «falla». Si el agente dice «fallo» en la conversación, el interesado lee
  «fallo» en el chat y «Falla» en su Excel, en la misma sesión. Esta spec no
  puede evitar esa asimetría: sólo puede elegir dónde ponerla y dejarlo
  escrito.

## 3. Criterios de aceptación

Delivery a enterprise-grade product (executed, observed, and verified),
leverage on `.claude/agents/testing/production-validator.md` to run old and new UAT/Test cases in the local and target (remote) environment.

1. **La terminología aplica sin que el agente la pida.** Existe un test que
   demuestra que las reglas de terminología están en el contexto de **cada**
   turno, no detrás de una herramienta de consulta.
2. **La decisión falla/fallo está escrita y es ejecutable.** El documento dice
   qué texto usa cada palabra y por qué, sin ambigüedad: un implementador puede
   aplicarla sin volver a preguntar.
3. **El entregable no cambia.** `tests/export/test_golden.py` pasa entero sin
   modificar, y los encabezados siguen idénticos al fixture del benchmark.
4. **La fuga de inglés baja.** Sobre un guion de conversación que ejercite los
   términos que hoy se filtran (`standby`, `P-F interval`, `failure finding`,
   `spare`), la salida usa el equivalente en español acordado, o lo acompaña
   entre paréntesis la primera vez.
5. **`GLOSARIO.md` sirve a sus dos públicos y lo dice.** Conserva la tabla de
   correspondencia para quien programa y añade, separada y marcada, la parte
   que gobierna cómo habla el agente. Queda explícito cuál de las dos partes
   está conectada al contexto y cuál no.
6. **Sin regresión de la base de conocimiento.** `consult_handbook` sigue
   devolviendo lo que devolvía sobre las dos fuentes actuales.

## 4. Notas de arquitectura

**Dónde conectar la terminología: en el prompt, no en la búsqueda.** Es la
decisión central y el repo ya aprendió esta lección en carne propia.
`factory.py:144-151` documenta que el estado de la sesión se inyectaba sólo si
el agente llamaba a `get_progress`, y el resultado medido fue *«31 turnos, 0
modos de falla registrados, el agente repreguntando cosas que él mismo marcaba
con ✔ ya lo dijiste»*. Por eso hoy el digest va en **cada turno**.

Una regla de terminología tiene la misma forma: gobierna cada frase que el
agente escribe, así que no puede depender de que decida buscarla. Añadir
`GLOSARIO.md` a `_SOURCES` (`handbook.py:16`) lo vuelve *buscable* vía
`consult_handbook`, que es una herramienta que el agente elige llamar — el modo
de fallo exacto que ya costó caro. **Las reglas de habla van en
`INSTRUCTIONS_ES`; la tabla de correspondencia puede ir a `_SOURCES` si se
quiere, pero eso es para responder «¿en qué columna cae esto?», no para
gobernar el vocabulario.**

**Presupuesto de contexto.** `INSTRUCTIONS_ES` son ~9 KB y compiten con el
digest de sesión en cada turno. Las 25 filas de la tabla de correspondencia no
caben ahí y no hacen falta: lo que gobierna el habla son unas pocas reglas
(qué palabra usar para el concepto central, qué hacer con un término en inglés
sin traducción cómoda, y la lista corta de equivalencias que hoy se filtran).
Meter la tabla entera desplazaría contexto útil por un beneficio nulo.

**Sobre falla/fallo — la decisión y su costo.** Las tres opciones reales:

- **(a) «Fallo» en la conversación, «Falla» en el Excel.** Es lo que pidió el
  interesado, tomado literalmente. Costo: el mismo concepto aparece con dos
  palabras en la misma sesión, y la columna que el agente nombra al explicar
  no coincide con la que el cliente lee. En un método donde el agente cita
  columnas constantemente, esa fricción es diaria.
- **(b) «Falla» en todo.** Coherencia total y coste cero de implementación;
  ignora el pedido.
- **(c) «Fallo» en la conversación, con la columna citada siempre verbatim
  entre comillas.** El agente dice «el fallo funcional» al razonar, y
  «la columna "Falla Funcional"» al referirse al entregable. Preserva el pedido
  y elimina la contradicción en el punto donde más molesta.

**Recomendada: (c).** Es la única que respeta el pedido sin romper la
correspondencia con el papel que el cliente tiene delante. Requiere una regla
extra en el prompt —citar nombres de columna verbatim y entrecomillados— que
además tiene valor propio: hoy el agente parafrasea nombres de columna y eso ya
confundió al interesado en el hallazgo 1.

**Antes de implementar (c), confirmar el mercado.** El interesado dijo «mercado
español». El resto del proyecto está escrito en español latinoamericano y el
cliente del benchmark usa «falla». Si el destinatario real es Latinoamérica, la
decisión correcta es (b) y esta spec se cierra sin tocar código. **Es la única
pregunta que esta spec no puede responder sola.**

## 5. Tareas

1. [ ] Confirmar el mercado destinatario y, con eso, elegir entre (b) y (c).
       Si es (b), cerrar la spec dejando escrita la decisión y saltar a la
       tarea 5.
2. [ ] Reescribir `docs/GLOSARIO.md` en dos partes marcadas: la tabla de
       correspondencia actual (para quien programa, no conectada) y un
       contrato de terminología corto (el que gobierna al agente).
3. [ ] Llevar el contrato de terminología a `INSTRUCTIONS_ES`: palabra elegida
       para el concepto central, regla de citar nombres de columna verbatim y
       entrecomillados, y la lista de equivalencias en español para los cuatro
       términos que hoy se filtran.
4. [ ] Test del criterio 1: demostrar que las reglas viajan en cada turno y no
       detrás de `consult_handbook`.
5. [ ] Test del criterio 3: `test_golden.py` pasa sin modificar y los
       encabezados siguen idénticos al fixture.
6. [ ] Verificar con `spec-verifier` antes del PR (`.claude/rules/specs.md:22`)
       y con `production-validator` en local.

## Supuestos

- SUPUESTO: el pedido de «fallo» es sobre la **conversación**, no sobre el
  entregable. El interesado nunca pidió cambiar el Excel, y no podría hacerse
  sin romper el dialecto del cliente. Si lo que quería era el entregable, esta
  spec no lo cubre y hay que reabrir la conversación con él.
- SUPUESTO: la fuga de inglés se resuelve con una lista corta de
  equivalencias. Son 4 términos distintos en 154 K caracteres; si aparecieran
  muchos más, la solución sería otra (un paso de revisión, no una lista).
- SUPUESTO: la tabla de correspondencia sigue siendo útil para quien programa.
  Si al reescribirla se ve que nadie la consulta, conviene borrarla en vez de
  mantener dos documentos.
