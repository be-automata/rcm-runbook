# Glosario y terminología para el mercado español

> AUTOSUFICIENTE: ejecutable en una sesión nueva, por alguien que no
> participó de la conversación que la originó.

## 1. Alcance

El interesado pidió, en el UAT del 09–11 ago 2026, «definir un glosario de
terminología en el contexto del agente» y usar **«fallo» en vez de «falla»**
para el mercado español. El mercado se confirmó: **España**.

Al investigarlo, falla/fallo resultó **no ser el problema principal**. El
proyecto habla español latinoamericano en sitios que un ingeniero español no
reconoce —«AMEF» en vez de AMFE, «RPN» en vez de NPR, «paro» por parada— y
tiene una **etiqueta de frecuencia que induce a un error de factor 4 en
dirección insegura**. Esta spec cubre el vocabulario entero, no una palabra.

Hallazgo 4 de esa ronda.

### Entra

- Conectar un contrato de terminología al contexto del agente, de forma que
  aplique siempre y no dependa de que el agente decida consultarlo.
- Fijar el eje **fallo / avería** según la norma española, y el alcance exacto
  de qué texto cambia y qué texto no puede cambiar.
- Las cuatro equivalencias de los términos ingleses que hoy se filtran.
- Las correcciones de registro latinoamericano en **prosa y código nuestro**
  (no en el fixture congelado).
- Resolver la **colisión de «fallo»**: hoy el proyecto ya usa esa palabra para
  los errores de software.
- Reescribir `docs/GLOSARIO.md` para sus dos públicos.

### NO entra (explícito)

- Cambiar los encabezados del Excel, los nombres de hoja o los valores del
  MENU. Están congelados verbatim contra el benchmark del cliente y hay dos
  golden tests que lo blindan (`tests/export/test_golden.py:26-30`). El
  entregable seguirá diciendo «Falla Funcional», «AMEF», «RPN», «Operar hasta
  la falla». El agente los **cita**, no los traduce.
- Renombrar identificadores del código (`FailureMode`, `failure_mode_id`).
- **Cambiar la etiqueta `Bi-Anual` del catálogo.** Es un cambio del MENU del
  cliente, de la misma familia que `Quinquenal`, y necesita su propia decisión
  — pero la mitigación que **sí** entra acá está en Notas de arquitectura, y
  es urgente.

## Pre-requisitos

- **Mercado: España**, confirmado por el responsable del producto el
  14-ago-2026. Descarta dejar las cosas como están.

- **El glosario existe y el agente no lo ve.** Verificado:
  `docs/GLOSARIO.md` (50 líneas) sólo se referencia en un **docstring de
  módulo** (`instructions_es.py:1`), que no entra en el contexto del modelo. Y
  la base de conocimiento carga dos ficheros, ninguno es el glosario
  (`knowledge/handbook.py:16`).

- **Qué es hoy `GLOSARIO.md`**, que no es lo que su nombre sugiere: una tabla
  de correspondencia término ↔ identificador ↔ columna ↔ herramienta, para
  quien programa. No contiene ninguna regla sobre **cómo debe hablar el
  agente**. Conectarlo tal cual no resuelve el pedido.

- **Medición sobre la sesión real de UAT** (154 K caracteres de salida):
  `falla*` **411**, `fallo*` **0**. Fuga de inglés: `standby` ×11,
  `P-F interval` ×5, `failure finding`, `spare` — **18 en total**. Ninguno de
  los cuatro existe como cadena de salida en `src/`: la fuga es del modelo, no
  del producto, así que se corrige con regla de prompt y no con reemplazos.

- **Lo que dice la norma española.** UNE-EN 13306:2018, *Mantenimiento.
  Terminología del mantenimiento* (versión oficial de EN 13306:2017):

  | Concepto | Término normativo | Apartado |
  |---|---|---|
  | failure | **fallo** — «cese de la aptitud… para realizar una función requerida» (un **evento**) | 5.1 |
  | fault | **avería** — «**estado** de un elemento caracterizado por la inaptitud…» | 6.1 |
  | failure mode | **modo de fallo** — «modo de avería» queda **desaconsejado** | 5.2 |
  | hidden failure | **fallo oculto** | 5.12 |
  | spare part | **repuesto** | 3.5 |
  | standby | **estado de espera**, **redundancia en espera** | 6.11 / 4.8 |

  La nota 5.1 es literal: *«El "fallo" es un evento que se debe diferenciar de
  la "avería", que es un estado»*.

  Dos avisos que evitan errores de atribución:

  - **`fallo funcional`, `intervalo P-F` y `failure finding` NO están en la
    13306**, en ninguna edición. Vienen de SAE JA1011/JA1012. Escribir «fallo
    funcional (UNE-EN 13306)» sería una atribución falsa.
  - **No existe ISO 14224 en español.** `UNE-EN ISO 14224:2016` está
    *ratificada, no traducida*: AENOR la publica sólo en inglés. El agente
    **nunca** debe decir «según ISO 14224, en español se dice X». Las
    traducciones que circulan son latinoamericanas y no oficiales.

  Trazabilidad: la 13306 es norma de pago y se verificó sobre copias no
  autorizadas, con corroboración cruzada (preview oficial de iteh.ai para 3.5,
  coherencia de numeración con BS EN 13306:2010 leída íntegra, ficha de AENOR).
  **Si el glosario va a citarla formalmente, la vía limpia es comprarla.**

## 3. Criterios de aceptación

Delivery a enterprise-grade product (executed, observed, and verified),
leverage on `.claude/agents/testing/production-validator.md` to run old and new UAT/Test cases in the local and target (remote) environment.

1. **La terminología aplica sin que el agente la pida.** Un test demuestra que
   las reglas están en el contexto de **cada** turno, no detrás de una
   herramienta de consulta.
2. **El eje fallo/avería es correcto y no se pasa de listo.** El agente usa
   «fallo» para el evento y todos sus compuestos, y «avería» **sólo** para el
   estado. En particular **nunca** dice «avería oculta»: en RCM el *hidden
   failure* es el evento (5.12), no el estado latente (6.2), y confundirlos es
   un error técnico, no de registro.
3. **Toda cadena congelada se cita verbatim y entrecomillada.** No sólo los
   nombres de columna: también los de hoja y **los valores del MENU**
   (frecuencias, disciplinas, patrones, etiquetas de política). Comprobable
   sobre un guion que ejercite un rechazo de catálogo.
4. **La fuga de inglés baja.** Sobre un guion que ejercite los cuatro términos,
   la salida usa el equivalente español acordado; `FFI` se mantiene como sigla,
   glosada en español la primera vez.
5. **«Fallo» deja de ser ambiguo.** El error de software ya no se llama «fallo
   técnico» en ningún texto que vea el cliente.
6. **El entregable no cambia.** `tests/export/test_golden.py` pasa entero sin
   modificar.
7. **`GLOSARIO.md` sirve a sus dos públicos y lo dice**, con la parte conectada
   al contexto marcada como tal.
8. **Sin regresión de la base de conocimiento.** `consult_handbook` sigue
   devolviendo lo que devolvía.

## 4. Notas de arquitectura

**Dónde conectar la terminología: en el prompt, no en la búsqueda.** El repo ya
aprendió esta lección. `factory.py:144-151` documenta que el estado de sesión
se inyectaba sólo si el agente llamaba a `get_progress`, con resultado medido:
*«31 turnos, 0 modos de falla registrados, el agente repreguntando cosas que él
mismo marcaba con ✔ ya lo dijiste»*. Una regla de terminología gobierna cada
frase, así que no puede depender de que el agente decida buscarla. Añadir
`GLOSARIO.md` a `_SOURCES` lo vuelve *buscable* vía `consult_handbook` — el
modo de fallo exacto que ya costó caro. **Las reglas de habla van en
`INSTRUCTIONS_ES`; la tabla de correspondencia puede ir a `_SOURCES`.**

**DECIDIDO — alcance: verbatim para toda cadena congelada, no sólo columnas.**
Se evaluaron tres opciones: (a) «fallo» en la conversación sin más; (c) «fallo»
citando los **nombres de columna** verbatim; y **(d) «fallo» citando verbatim
toda cadena congelada — columnas, hojas y valores del MENU — más una frase de
encuadre única al inicio y en la exportación**, del tipo *«su libro escribe
"falla"; yo diré "fallo" al razonar y citaré sus columnas y valores tal cual»*.

**(d), y la diferencia no es cosmética: los nombres de columna no son lo que el
ingeniero teclea; los valores del catálogo sí.** El sistema ya los emite
verbatim —`tools.py` devuelve `Válidas: {…}` en cada rechazo, y `tools.py:871`
ordena escribir la frecuencia «EXACTAMENTE como se escribe aquí»—. Si el agente
hispaniza «Búsqueda de Falla» → «Búsqueda de Fallos» en su prosa y el ingeniero
copia eso, el validador lo rechaza. Ahí la asimetría deja de ser fricción y
pasa a ser **fallo operativo**.

**Riesgo real de la asimetría, dicho sin inflar.** Como problema de
*comprensión* es menor: «falla» y «fallo» son mutuamente transparentes y ningún
ingeniero español duda de qué columna es «Falla Funcional». Escala en tres
cosas concretas: el **vocabulario controlado** de arriba (la grave); la
**trazabilidad**, porque copiar del chat y buscar en el libro falla; y la
**credibilidad** ante un ingeniero mirando una demo, donde una inconsistencia
visible y no explicada se lee como descuido, mientras que una frase de encuadre
la convierte en decisión deliberada y demuestra que se respeta su formato.

**Colisión que hay que resolver: «fallo» ya significa otra cosa acá.**
`app.py:230` sirve al cliente *«El sistema tuvo un fallo técnico…»*, existe
`_FALLOS_DEL_PROVEEDOR` (`app.py:211`), e `instructions_es.py:76-96` monta una
sección entera sobre distinguir «Regla del método» de «**Fallo técnico**». Si
«fallo» pasa a ser el término del dominio, esa sección queda ambigua justo
donde exige precisión. **Renombrar el error de software a «error del
sistema».**

**Los cuatro términos ingleses.** Ninguno se deja en inglés: en los cuatro hay
equivalente asentado en España. La única sigla que se mantiene es `FFI`.

| Inglés | En España | Nota |
|---|---|---|
| `standby` | **«en reserva»** (el equipo) / **«en espera»** (el modelo de fiabilidad) | UNE-EN 13306 4.8 y 6.11. **«de respaldo» es calco, no usar.** |
| `P-F interval` | **«intervalo P-F»**, «curva P-F», «punto P / fallo potencial», «punto F / fallo funcional» | **No se deja en inglés en España** — se verificó en publicaciones técnicas españolas del sector. No está en la 13306. |
| `failure finding` | **«búsqueda de fallos ocultos»**; la tarea, «prueba funcional» | **Nunca «búsqueda de averías»**: invertiría el sentido — 13306 8.7/8.8 son *troubleshooting*. «Mantenimiento detectivo» es registro latinoamericano. |
| `spare` | **«repuesto»** | Es el término **normativo** (13306 3.5); «recambio» es ahí *replacement item*. No suena latinoamericano en España. |

**URGENTE y de la familia de `Quinquenal`: «Bi-Anual» induce un error de factor
4 en dirección insegura.** Verificado: `catalogs.py:124` mapea `"Bi-Anual"` a
**17 520 h = 2 años** (o sea *bienal*), y la RAE define **bianual = dos veces al
año**. Un ingeniero español lee «cada seis meses» donde el sistema calcula
«cada dos años». Lo mismo con `Tri-Anual` (3 años) y `Tetra-Anual` (4).

Y es **peor que `Quinquenal`**: aquel se dejó fuera de `FRECUENCIA_EN_HORAS` a
propósito (`catalogs.py:89-91`), así que no puede compararse en silencio; estos
tres **sí están** en el mapa y `compliance.py:279` los compara contra el FFI. En
una tarea de búsqueda de fallos ocultos sobre un dispositivo de protección, esa
lectura significa probarlo **cuatro veces menos seguido** de lo calculado.

Cambiar la etiqueta es un cambio del MENU del cliente y va aparte. **La
mitigación que sí entra en esta spec y no toca el catálogo: que el agente
glose siempre la frecuencia en horas** — «"Bi-Anual" (en su catálogo, cada 2
años = 17.520 h)»— y pregunte ante la duda. Es una regla de prompt y elimina la
ambigüedad en el punto donde se decide.

**Registro latinoamericano en prosa y código nuestro.** Lo que sigue **no**
está congelado y se puede corregir. Lo más visible primero:

- `instructions_es.py:4` dice *«un ingeniero de **confiabilidad** experto»* y
  dos líneas más abajo *«Mantenimiento Centrado en la **Fiabilidad**»*. **El
  prompt se contradice consigo mismo en seis líneas.** España: *fiabilidad*.
  Una palabra, y es la primera frase que lee el cliente.
- `monitoreo` → **`monitorización`** (término normativo, 13306 8.2), y
  `confiable` → `fiable` (`catalogs.py:378`, `domain.py:143`, `scoring.py:41`,
  `decision_logic.py:117`).
- `costos` → **`costes`** (`tools.py`, `catalogs.py:110`); `factory.py:145` ya
  escribe «coste».
- `computadora` → **`ordenador`** (`demo_page.py:9`), que está en la página de
  la demo, o sea de lo primero que ve el cliente.
- **`MECHANISMS_ES` y `CAUSE_CATEGORIES_ES`** (`catalogs.py:301-327`) dicen
  «Falla Mecánica», «Falla Eléctrica», etc. Un comentario del propio fichero
  aclara que **el MENU del benchmark no los enumera**: son invención nuestra,
  **no están congelados**, y pueden pasar a «Fallo Mecánico».

**Lo que está congelado y sólo se puede citar y glosar.** El agente dice
«AMEF» en su propia prosa (`instructions_es.py:20`; **68 apariciones en el
repo**), y en España el término es **AMFE**. Igual con **RPN** (allí **NPR**),
**TPEF** («tiempo medio entre fallos», MTBF — «promedio» es registro
latinoamericano), y **«REQUIERE PARO DEL EQUIPO?»**, donde *paro* en España es
desempleo o huelga y lo correcto es *parada*. También «Catorcenal» (registro de
nómina mexicana) y «Tetramestral» (no está en el DRAE; sería *cuatrimestral*).

Estas son las que más pueden chirriar —probablemente **más que falla/fallo**—
y la regla de encuadre existe justamente para ellas: se citan tal cual, con la
glosa española la primera vez.

## 5. Tareas

1. [x] ~~Confirmar el mercado.~~ **España.**
2. [ ] Reescribir `docs/GLOSARIO.md` en dos partes marcadas: la tabla de
       correspondencia (para quien programa, no conectada) y el contrato de
       terminología (el que gobierna al agente).
3. [ ] Llevar el contrato a `INSTRUCTIONS_ES`: eje fallo/avería, regla verbatim
       para toda cadena congelada, frase de encuadre, las cuatro equivalencias,
       y la glosa obligatoria de frecuencias en horas.
4. [ ] Renombrar el error de software a «error del sistema» (`app.py:211-246`,
       `instructions_es.py:76-96`) para deshacer la colisión.
5. [ ] Correcciones de registro de una palabra: `confiabilidad`→`fiabilidad`,
       `monitoreo`→`monitorización`, `costos`→`costes`,
       `computadora`→`ordenador`, y `MECHANISMS_ES`/`CAUSE_CATEGORIES_ES`.
6. [ ] Test del criterio 1 (las reglas viajan en cada turno) y del criterio 3
       (una cadena congelada se cita verbatim).
7. [ ] Test del criterio 6: `test_golden.py` pasa sin modificar.
8. [ ] `spec-verifier` antes del PR (`.claude/rules/specs.md:22`) y
       `production-validator` en local.

## Supuestos

- SUPUESTO: el cliente del benchmark **no** es el destinatario del producto. El
  fixture trae la fila «OPINION DE EXPERTOS (REPSOL)» —una operadora española—
  pero el libro está escrito en español latinoamericano, probablemente de un
  activo americano. Si resultara que ese cliente **sí** es el destinatario, la
  asimetría deja de ser tolerable y habría que reabrir la congelación de
  encabezados, que es un cambio de otra magnitud.
- SUPUESTO: «intervalo de búsqueda de fallos» es el sintagma español asentado
  para FFI. Verificado que la sigla circula y que el ámbito nuclear español usa
  «intervalo de vigilancia»; el sintagma exacto **no** se pudo verificar.
- SUPUESTO: cambiar `MECHANISMS_ES` no rompe sesiones guardadas. Comprobar si
  algún estado persistido guarda esas cadenas antes de tocarlas.
- SUPUESTO: la fuga de inglés se resuelve con una lista corta. Son 4 términos
  en 154 K caracteres; si aparecieran muchos más, la solución sería otra.
