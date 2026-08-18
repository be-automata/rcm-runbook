# Registro de cambios

Todos los cambios relevantes de este proyecto. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/), y las versiones
[Versionado Semántico](https://semver.org/lang/es/).

La versión vive en dos sitios y tienen que coincidir: `VERSION` y el campo
`version` de `pyproject.toml`. `package.json` es del worker de Cloudflare, que es
otro artefacto y lleva su propio número.

## [No publicado]

## [0.2.1] — 2026-08-18

### Corregido

- **«Bi-Anual» vale dos años y la RAE dice que bianual es dos veces al año.** Un
  factor 4 en la dirección insegura si el interesado lo lee como semestral, y
  sobre una tarea de búsqueda de fallos ocultos eso significa probar el
  dispositivo de protección cuatro veces menos seguido de lo calculado.
  «Tri-Anual» y «Tetra-Anual» tienen el mismo problema. La etiqueta no se puede
  cambiar —es el MENU del cliente y va verbatim al Excel— así que el agente pasa
  a glosar siempre la frecuencia en horas.
- **El agente declaraba imposibles correcciones que sí podía hacer.** Dijo al
  interesado que «el sistema no permite editar retroactivamente las
  descripciones» cuando `reemplazar=True` existe y el propio prompt lo
  documentaba. Ahora enumera qué acepta corregirse y tiene prohibido declarar un
  límite del sistema que no haya observado en un `❌` de herramienta. Un test
  compara esa lista contra las firmas reales para que no se pudra.
- **El prompt se contradecía consigo mismo en seis líneas**: «ingeniero de
  confiabilidad» y, dos más abajo, «Mantenimiento Centrado en la Fiabilidad». El
  mercado es España: fiabilidad.

### Corregido

- **Un sello por artefacto: los controles ya no invalidan la decisión.**
  `failure_mode_snapshot` sellaba con un mismo hash la valoración S/O/D y la
  decisión RCM, que tienen insumos distintos, e incluía los controles — que
  justifican la Detección y que `decide()` no lee. Añadir un control no podía
  cambiar la política pero invalidaba la decisión que la contiene: 31 de 32 en la
  sesión de UAT. El bloqueador era irresoluble por su propio camino y volvía a
  pedir cuatro firmas humanas JA1011 sin motivo. Se parte en `score_snapshot`
  (con controles) y `decision_snapshot` (sólo lo que `decide()` puede leer).
- **El sello de la decisión sellaba once campos y `decide()` lee cuatro.**
  Corregir una errata en la descripción de un modo marcaba su decisión como
  obsoleta. Los siete campos descriptivos salen del sello de la decisión y siguen
  en el de la valoración, que es donde pertenecen.
- **31 bloqueadores fantasma.** `stale_decisions()` devolvía la unión de
  valoraciones y decisiones obsoletas, y dos compuertas etiquetaban la misma
  lista de dos maneras. Ninguna valoración estaba desfasada. Se parte en
  `stale_scores()` y `stale_decisions()`.
- **El aviso del bloque TPEF pisaba una fila ya poblada** en la hoja PLAN,
  dejando sus horas, años y fuente sin el modo al que pertenecen.
- **El guion de re-sellado no reconocía el volcado de producción** y lo procesaba
  sin tocar nada, devolviendo éxito. Ahora reconoce las tres envolturas y rechaza
  con salida 2 lo que no es una sesión.

### Añadido

- `scripts/resellar_decisiones.py`: migración de datos que re-sella las
  decisiones con la fórmula nueva. No re-ejecuta la lógica de decisión, así que
  no vuelve a pedir las firmas HITL. Vuelca el estado previo, aplica, relee del
  disco y compara.
- Aceptación de sellos de la fórmula anterior, reconstruidos por prefijos de la
  lista de controles. Elimina la ventana en la que desplegar dejaría el estado
  vivo peor que antes.
- `RCMSession.decisiones_sin_sello_canonico()`: el predicado estricto, que es
  también la condición de retirada de esa compatibilidad.
- Cuatro specs en `specs/` para el resto del feedback de UAT: veracidad de lo que
  el agente afirma, glosario y terminología, supersesión de modos duplicados, y
  la de este cambio.

### Cambiado

- Los documentos de UAT se auditaron caso por caso (195 revisados) contra el
  estado real del código. Cinco criterios obsoletos corregidos.

## [0.1.1] — 2026-08-13

### Corregido

- **El identificador del modo de falla no llegaba al Excel.** El agente cita
  `FM-019` cientos de veces en la conversación y el libro no traía el código en
  ninguna columna, así que no había forma de cruzar una fila con lo hablado. Va
  en la columna A, fuera del rango de encabezados congelado contra el benchmark
  del cliente. (#1)
- **28 de 60 filas salían sin clasificar** como falla evidente u oculta, sin
  nada que explicara por qué. El dato existía en el estado y el exportador no lo
  miraba. (#1)
- **La hoja PLAN descartaba en silencio los modos sin decisión**: 49 filas contra
  las 60 del AMEF, escondiendo 8 de las 11 fallas ocultas del análisis. (#1)
- **Un borrador no se distinguía de un entregable terminado** salvo por el nombre
  del fichero, que no viaja con una captura de pantalla. (#1)
- **El centinela decía «evidente» sobre una falla que la decisión declara
  oculta** cuando faltaba el efecto, y «sin decisión RCM» en filas que sí tenían
  decisión. (#2)
- **CI llevaba roto desde el 2 de agosto** por una llave que sólo existía en el
  `.env`, y con él cuatro pruebas de autenticación del WebSocket se saltaban en
  silencio. (#3)

## [0.1.0] — 2026-08-02

Primera versión pública. Facilitador RCM conversacional: guía un análisis de
Mantenimiento Centrado en la Fiabilidad por sus seis fases con herramientas
deterministas —lógica de decisión SAE JA1011/JA1012, valoración S/O/D según SAE
J1739, cálculo de FFI—, y exporta el entregable en el dialecto Excel del cliente
(hojas AMEF, PLAN DE MANTENIMIENTO, SAE-J1739 y AUDITORIA RCM).

Publicado bajo Apache 2.0.
