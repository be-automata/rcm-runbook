# Veracidad de lo que el agente afirma sobre el entregable

> AUTOSUFICIENTE: ejecutable en una sesión nueva, por alguien que no
> participó de la conversación que la originó.

## 1. Alcance

Durante el UAT del 09–11 ago 2026 el agente afirmó **dos veces** que el Excel
exportado ya contenía columnas con los códigos `FF-` y `FM-`. No las contenía.
El interesado tuvo que abrir el fichero y desmentirlo. Esta feature hace que
una afirmación así sea difícil de sostener: el resultado de `export_excel`
pasa a describir lo que el fichero realmente tiene, y el prompt prohíbe
explícitamente afirmar propiedades del entregable que ninguna herramienta haya
devuelto.

Origen: hallazgo de la ronda de UAT, declarado fuera de alcance en
[`trazabilidad-y-clasificacion-en-el-excel.md`](trazabilidad-y-clasificacion-en-el-excel.md)
porque no se arregla en el exportador. Las citas textuales están abajo, en
Pre-requisitos, para que esta spec no dependa de aquella conversación.

### Entra

- Que `export_excel` devuelva un **manifiesto verificable** de lo que quedó en
  el fichero: hojas, columnas presentes, número de filas de datos por hoja, si
  es borrador, y cuántos defectos lleva adjuntos.
- Una regla de veracidad en `INSTRUCTIONS_ES`, con el alcance correcto: no
  afirmar como hecho ninguna propiedad de un artefacto que no venga de un
  resultado de herramienta.
- Que el agente no declare imposible una capacidad que sí existe (ver el
  segundo caso en Pre-requisitos).
- Un eval que falle si el agente afirma haber cambiado algo sin la llamada que
  lo respalde.

### NO entra (explícito)

- Cambiar la forma del entregable. Esta spec no toca `rows.py` ni las
  cabeceras congeladas; el manifiesto **describe**, no modifica.
- Verificar afirmaciones del agente sobre el **dominio** (que un modo sea
  creíble, que un TPEF sea razonable). Eso es juicio técnico y lo valida el
  interesado; acá sólo se trata de afirmaciones sobre **artefactos y acciones
  propias**, que son comprobables mecánicamente.
- Impedir que el agente se equivoque al razonar. El objetivo es que no
  **afirme como hecho consumado** algo que no ocurrió, no que sea infalible.
- Los hallazgos 3, 4 y 5 de la misma ronda de UAT (costo-beneficio, glosario,
  colaboración asíncrona). El glosario tiene su propia spec.

## Pre-requisitos

- **Las dos citas que originan esta spec.** Están acá porque son la
  especificación del defecto, no color narrativo.

  Primera, tras pedirle el Excel con los códigos en columnas — el agente
  responde afirmando un hecho sobre un fichero que nunca inspeccionó:

  > *"el Excel que exporté ya contiene los **códigos FF- y FM-** en columnas
  > separadas. El sistema los genera automáticamente cuando exporta."*

  Lo repitió en el turno siguiente. El interesado tuvo que abrir el fichero:

  > *"No aparecen los códigos FF- y FM- visibles en columnas. No se crearon las
  > columnas."*

  Segunda, un caso distinto y también falso — declarar imposible algo que la
  herramienta sí permite:

  > *"Lamentablemente, el sistema no permite editar retroactivamente las
  > descripciones de forma masiva"*

  `record_failure_mode` acepta `reemplazar=True` (`tools.py:413`, `:426`) y el
  propio prompt lo documenta (`instructions_es.py:137-143`). El agente
  desconoció una capacidad propia y trasladó al interesado un límite
  inexistente.

- **Por qué el prompt actual no lo evita.** `instructions_es.py:141-143` ya
  dice *"No sigas adelante dando por aplicada una corrección que la herramienta
  no aceptó"*. La regla existe pero está acotada a **correcciones rechazadas**;
  lo que ocurrió fue afirmar una propiedad del **entregable**, que ninguna
  regla cubre.

- **Por qué el agente no tenía cómo saberlo.** `export_excel` (`tools.py:988`)
  devuelve hoy sólo el nombre del fichero, el enlace de descarga y las
  advertencias JA1011:

  ```
  ✔ Entregable definitivo exportado (AMEF_P-101.xlsx).
  Entregue este enlace al interesado, tal cual: [Descargar el Excel](/exports/…)
  ```

  Ni una palabra sobre el contenido. El agente no tenía contra qué contrastar
  su afirmación y nada en el resultado la contradecía. **Esa es la causa raíz
  y el motivo de que la spec no sea sólo de prompt.**

## 3. Criterios de aceptación

Delivery a enterprise-grade product (executed, observed, and verified),
leverage on `.claude/agents/testing/production-validator.md` to run old and new UAT/Test cases in the local and target (remote) environment.

1. **El resultado de exportar describe el fichero.** Tras `export_excel`, el
   texto devuelto permite responder sin abrir el `.xlsx`: qué hojas tiene,
   qué columnas de la tabla principal, cuántas filas de datos por hoja, si es
   borrador, y cuántos defectos van adjuntos en AUDITORIA. Los números salen
   del libro efectivamente escrito, no de recalcular el estado por otro camino.
2. **El manifiesto habría desmentido la afirmación original.** Reproducido el
   escenario del UAT —un análisis sin columnas de código exportado como
   borrador— el manifiesto no menciona ninguna columna `FF-`/`FM-` como
   columna. Verificable como test.
3. **La regla de veracidad está en el prompt y es específica.** No un «sé
   honesto» genérico: dice qué clase de afirmación está prohibida (propiedades
   de artefactos y acciones propias no respaldadas por un resultado de
   herramienta) y qué hacer en su lugar (exportar y leer el manifiesto, o
   decir que no se sabe).
4. **El agente no declara imposible lo que puede hacer.** El prompt enumera,
   en un solo lugar, las capacidades de corrección que existen
   (`reemplazar=True` en `record_function`, `record_failure_mode`,
   `record_task`) y prohíbe afirmar límites del sistema que no haya observado
   en un `❌` de herramienta.
5. **Hay un eval que falla si el defecto vuelve.** Sobre una conversación
   guionizada donde se pide un cambio y el agente no lo ejecuta, el eval falla
   si la respuesta afirma que el cambio está hecho. Corre sin llamar al modelo
   real, o queda marcado `eval` y documentado como opt-in.
6. **Sin regresión de la compuerta ni del enlace.** `export_excel` sigue
   rechazando el definitivo con el análisis incompleto, y sigue devolviendo el
   enlace `[Descargar el Excel](/exports/…)` tal cual, en su propia línea
   (`instructions_es.py:145-150` depende de ese formato exacto).

## 4. Notas de arquitectura

**El arreglo de fondo es de herramienta, no de prompt.** Un prompt que dice
«no mientas» compite con la tendencia del modelo a complacer, y se degrada con
cada turno que se aleja de la instrucción. Un resultado de herramienta que
enumera las columnas reales no se degrada: está en la ventana, es corto, y
contradice la afirmación falsa en el mismo turno en que se formularía. Por eso
el criterio 1 va primero y el 3 después: el prompt es el refuerzo, no la
defensa.

**Dónde se calcula el manifiesto.** Tiene que salir del **libro escrito**, no
de volver a proyectar la sesión. Si se recalcula desde `RCMSession` se está
describiendo lo que *debería* haberse escrito, que es exactamente el error que
esta spec persigue. `export_xlsx` (`excel.py`) ya devuelve el `Path`; lo
natural es leer el fichero recién guardado con `openpyxl`, o que
`build_workbook` devuelva el manifiesto junto al `Workbook`. La segunda opción
evita el round-trip pero vuelve a describir intención en vez de resultado; la
primera cuesta unos milisegundos —el libro completo se genera en ~50 ms para
63 modos— y describe el artefacto. **Preferir leer el fichero.**

**Tamaño del manifiesto.** Va en cada resultado de `export_excel`, así que
compite por contexto. Las 27 cabeceras de AMEF más las 20 de PLAN no caben sin
desplazar cosas útiles. Alcanza con: hojas, número de columnas por hoja,
número de filas de datos, presencia o ausencia de la columna de ID, si es
borrador, y el recuento de defectos. Si el interesado pregunta por una columna
concreta, el agente puede decir que la verifique en el fichero — que es la
respuesta honesta.

**Precedente en el repo.** `errors.py:30` documenta una lección aplicable:
adjuntar una nota larga a un mensaje de error hizo que el modelo la repitiera
en vez de actuar. El manifiesto tiene el mismo riesgo si se escribe como
párrafo. Formato tabular corto y sin adjetivos.

**Riesgo de la regla de veracidad.** Una prohibición demasiado amplia («no
afirmes nada que no hayas verificado») paraliza la conversación: el agente
empieza a hedgear cada frase y el interesado, que valoró justamente que el
agente sea proactivo, pierde eso. El alcance del criterio 3 está acotado a
propósito a **artefactos y acciones propias**.

## 5. Tareas

1. [ ] Construir el manifiesto leyendo el `.xlsx` recién escrito, y devolverlo
       desde `export_xlsx` junto al `Path`.
2. [ ] Incluirlo en el texto que devuelve `export_excel` (`tools.py:988-1010`),
       sin tocar el formato del enlace de descarga.
3. [ ] Añadir a `INSTRUCTIONS_ES` la regla de veracidad acotada (criterio 3) y
       la enumeración de capacidades de corrección (criterio 4).
4. [ ] Eval guionizado del criterio 5, en `tests/evals/`, siguiendo el patrón
       de `test_scenario_scripted_complete` (que corre en CI sin modelo real).
5. [ ] Test del criterio 2: reproducir el escenario del UAT y comprobar que el
       manifiesto no atribuye al fichero columnas que no tiene.
6. [ ] Verificar con `spec-verifier` antes del PR — lo exige
       `.claude/rules/specs.md:22` — y con `production-validator` en local.

## Supuestos

- SUPUESTO: el interesado lee el resultado de la herramienta a través de la
  respuesta del agente, no directamente. El manifiesto es para que **el
  agente** no pueda afirmar lo contrario; que además se lo muestre al
  interesado es deseable pero no es el mecanismo.
- SUPUESTO: los dos casos citados son la misma clase de defecto. Podrían
  tratarse por separado —uno es sobre el artefacto, el otro sobre las
  capacidades propias— pero comparten la forma: afirmar como hecho algo no
  observado. Si al implementar resultan pedir mecanismos distintos, partir la
  spec antes que forzarlos juntos.
- SUPUESTO: no hace falta impedir la afirmación falsa, sólo hacerla
  improbable y detectable. Un agente puede ignorar el manifiesto y mentir
  igual; lo que cambia es que ahora hay evidencia en el mismo turno y un eval
  que lo caza.
