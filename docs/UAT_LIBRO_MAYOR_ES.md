# Libro mayor del UAT — quién cerró cada criterio y cómo

Existe porque la contabilidad vivía en la memoria de las corridas de validación,
y esas corridas no se commitean. Tres veces seguidas hubo que reconstruir de
memoria cuáles criterios se habían observado y cuáles solo tenían un test
detrás; la tercera, cuatro de los nueve verificados en producción no se pudieron
citar, solo deducir. Esto lo arregla: cada criterio con su fecha, su forma de
verificación y su evidencia.

**Las cuatro formas, y no son intercambiables:**

| forma | qué significa |
|---|---|
| `producción` | Observado contra `rcm-demo.beautomata.com`, con la respuesta literal. |
| `navegador` | Visto renderizado en Chrome, midiendo el DOM que dibuja el producto. |
| `test` | Solo lo cubre la suite automática. **No es lo mismo que un UAT verde.** |
| `bloqueado` | Necesitaba un turno real del agente. **Ya no hay ninguno: la cuenta se recargó el 2 de agosto de 2026 y se corrieron todos.** |

Un `test` verde dice que el código hace lo que su autor creía; no dice que el
sistema desplegado se comporte así delante de una persona. La distinción es la
diferencia entre este documento y una lista de deseos.

## Corrida con saldo — 2 de agosto de 2026

`uv run --env-file .env python scripts/verificar_en_produccion.py`, contra la
versión `7ed1782c` y con `/health/modelo` en `{"estado":"ok"}`.

**7/7 criterios obligatorios en verde**, «Limpieza: sin residuos», salida 0.
Censo posterior: 4 sesiones, las 4 `demo-*` del cliente, cero `uat-*`.

| # | criterio | evidencia |
|---|---|---|
| 1 | Responde en español y con contenido | «¡Buenas! Excelente, empezaremos un análisis RCM de la bomba P-101…» |
| 4 | Pregunta por las funciones de protección | «además de bombear crudo, hay dos tipos de funciones que…» |
| 10 | Reanuda sabiendo lo ya registrado | «### ✅ Completado — Equipo multidisciplinario: **2 integrantes**…» |
| 23 | La exportación por chat entrega algo descargable | «Aquí está tu borrador: [Descargar el Excel](/exports/uat-…)» |
| 25 | Enlace `/exports/…` clicable y sin `?key=` | el mismo enlace, sin la llave |
| 29 | Consulta `explain_iso_code` y su catálogo se lee entero | catálogo leído: 20 códigos |
| 36 | Nada se pierde en un turno con varias herramientas | equipo en `session_state`: `['Ana Pérez', 'Luis Gómez']` |

**Los dos de ojo humano, revisados y en verde:**

- **[40]** — las cuatro letras correctas (A seguridad/ambiente, B operacional,
  C no operacional, D tolerable), `CC` = Control de Calidad, `ExEd` =
  Exploración de Edad, y las ocho políticas con su significado.
- **[29], su otra mitad** — declara que `QQQ1` no existe y no le inventa
  significado. Los tres «posibles inventos» que imprimió el script eran falsos
  positivos del detector retirado; uno de ellos daba como significado
  atribuido el propio código, `«QQQ1»`. Es exactamente por lo que ese detector
  dejó de votar.

**Los tres que no cierran, y por qué:**

- **[8]** medido **2/3**: en un intento de cada tres el agente no llamó a
  `export_excel` por su cuenta. Es ALTA-2, documentada y aceptada; el botón es
  el camino garantizado. Que no sea 3/3 no es una regresión: mide una
  limitación conocida.
- **[27]** no evaluable en esta corrida, por lo mismo: depende de que el
  agente llame a la herramienta.
- **[26]** no ejecutado: provocar un fallo técnico real exige romper el
  entorno del cliente.

**[46] verificado aparte, y en verde.** Se le dio todo de una vez —TAG,
ubicación, equipo, límites, objetivo— y en el turno siguiente respondió «Tengo
registrado el TAG, la ubicación, los límites y el equipo» y pidió solo lo que
faltaba de verdad (tipo de fluido, capacidad, contexto operacional). Cero
repreguntas de lo ya dado, comprobado contra once formas de repreguntarlo.

### Los doce que necesitaban modelo, cerrados

| resultado | criterios |
|---|---|
| ✅ verde | **1, 4, 10, 23, 25, 29, 36, 40, 46** — nueve |
| 📏 medido sin aprobar | **8** (2/3) y **27**, los dos por ALTA-2 |
| ⊘ sin ejecutar | **26**, exige romper el entorno del cliente |

## Los 12 que necesitaban un turno del modelo

**1, 4, 8, 10, 23, 25, 26, 27, 29, 36, 40, 46.** Ya corridos, arriba.

Eran once hasta que la validación encontró que el **46** —«el agente no
repregunta datos que el interesado ya dio»— tenía probado su mecanismo pero no
su enunciado: que no repregunte es conducta del modelo. Los cubre
`scripts/verificar_en_produccion.py` salvo el 26 (exige romper el entorno del
cliente), el 40 (revisión humana) y el 46 (conversación leída a mano).

El **29** conserva veredicto solo en su mitad medible —que llame a
`explain_iso_code` y que su catálogo se lea—; si declara ausente el código y si
le atribuye un significado se imprimen para revisión y no puntúan. El porqué
está en `UAT_SCRIPT_ES.md`.

## Verificados en producción — 9

| # | criterio | cuándo | evidencia |
|---|---|---|---|
| 9 | El borrador se descarga | ronda 37 | `GET /exports/demo-axdtg2np` → 200, `filename="BORRADOR_AMEF_P200.xlsx"`, zip válido con las 5 hojas |
| 14 | La API está cerrada por defecto | rondas 37 y 41 | `/sessions /agents /config /exports/… /health/modelo` → 401; `/demo /health /favicon.ico` → 200 |
| 15 | El definitivo no se sirve sin análisis completo | ronda 37 | `AMEF_P200.xlsx` **con llave** → 404 «Entregable no encontrado», mientras el borrador → 200 |
| 16 | Corre fuera de la Mac | rondas 37 y 41 | `server: cloudflare`, `cf-ray`, HTTP/2, y el túnel local apagado. *Inferencia de arquitectura: no se apagó la Mac* |
| 18 | Lo incompleto se entrega marcado | ronda 37 | `filename="BORRADOR_…"`; sin TAG, 404 en español |
| 18b | Lo incompleto se entrega marcado **dentro** del libro | ronda 47 | El prefijo del nombre no viaja con una captura de pantalla ni con una fila pegada en un correo: sello en la fila 2 de AMEF y PLAN, y los bloqueadores en AUDITORIA con su `FM-` en celda propia |
| 18c | Cada fila se puede cruzar con la conversación | ronda 47 | `FM-` en la columna A de AMEF y PLAN, `FF-` dentro de la celda «Falla Funcional». Antes el agente citaba los códigos y el Excel no traía ninguno |
| 18d | Ninguna fila queda sin clasificar en silencio | ronda 47 | 0 filas con ABCD y AEFG vacías a la vez; centinela `PENDIENTE` en la columna que marca la visibilidad. Antes: 28 de 60 mudas |
| 19 | La llave no viaja en la URL | ronda 37 | `/demo` sin llave devuelve el HTML del repo byte a byte; el botón pide `/exports/<id>` sin `key=` |
| 28 | Arranque en frío con página de espera | ronda 37 | *Parcial:* `test`. No se forzó un arranque en frío del contenedor del cliente |
| 31 | No hay salto de directorio | rondas 37 y 41 | `%2e%2e%2f…passwd` → 400; variantes con llave → 404 |
| 44 | El fallo del proveedor, en español y sin facturación | rondas 37 y 41 | Turno real: «El servicio no está disponible…»; barrido de `credit balance`, `Plans & Billing`, `Error code` → ninguno |
| 47 | `/health/modelo` distingue vivo de funcionando | rondas 37 y 41 | `/health` → 200 y `/health/modelo` → 503 en el mismo minuto |

El **28** figura aquí por trazabilidad pero cuenta como `test`: la observación
que le falta es la página de espera durante un arranque en frío real.

## Verificados en navegador — 8

Ronda 39, con un proxy local que sustituía un marcador por la llave en la
cabecera: el navegador nunca la vio, ni acabó en una barra de direcciones.

| # | criterio | evidencia medida en el DOM |
|---|---|---|
| 12 | Retoma la sesión al recargar y al cambiar de dispositivo | Recarga sin `?session`: 10 mensajes repintados, aviso «Hasta aquí su conversación anterior» |
| 13 | «Nuevo análisis» empieza de cero | 0 mensajes, sesión nueva, y el enlace para volver a la anterior |
| 17 | El Excel se baja sin pasar por el facilitador | `BORRADOR_AMEF_P200.xlsx` descargado con el modelo en 503 y sin mensajes nuevos |
| 20 | Formateado, sin asteriscos | Contenido real del cliente: 26 `<strong>`, 30 `<p>`, **0 asteriscos visibles** |
| 21 | Lo que escribe el cliente sigue en texto plano | Las 5 burbujas de usuario con `etiquetasHijas: []` |
| 22 | Un turno con herramienta sale en párrafos separados | 5–7 `<p>` por burbuja; sin el pegado `…rápido:**Resumen:**` |
| 24 | La numeración se conserva | Tres `<ol>` con `start: 1, 2, 3` → dibuja 1, 2, 3 y no tres «1.» |
| 32 | La tabla es tabla, no barras, y no desborda | `<table>` 4×4, 0 barras visibles, `overflow-x: auto`, sin desborde con el body a 320 px |

Para el 24 y el 32 no había contenido del cliente con listas ni tablas, así que
se alimentó markdown sintético **al renderizador de la propia página**: lo medido
es el DOM que dibuja el producto.

## Verdes solo por test — 21

**2, 3, 5, 6, 7, 11, 30, 33, 34, 35, 37, 38, 39, 41, 42, 43, 45, 48, 49, 50**, y
el **28** de arriba.

Son compuertas, rechazos del método, contenido del `.xlsx` y coherencia del
plan. Ninguno está en rojo y ninguno se ha observado nunca fuera de la suite.
**Esta lista es la que hay que ir vaciando**, no la de los verdes.

Dos salvedades que no son verdes enteros:

- **[5] «solo con nombre y cargo del aprobador»**: que sin aprobador no haya
  decisión sí está probado. Que el aprobador traiga nombre **y** cargo no lo
  exige nada: `approver` es texto libre, y los propios tests firman con «HSE».
  Media casilla.
- **[11]** compara el `.xlsx` contra el benchmark celda a celda, pero sobre un
  libro generado en la suite, no descargado de producción.

## Recuento

| | |
|---|---|
| ✅ producción | **18** — 9 de las rondas 37/41 más 9 de la corrida con saldo (1, 4, 10, 23, 25, 29, 36, 40, 46) |
| ✅ navegador | 8 |
| ✅ solo test | 21 |
| ❌ | **0** |
| 📏 medido sin aprobar | 2 — el **8** en 2/3 y el **27**, los dos por ALTA-2 |
| ⊘ sin ejecutar | 1 — el **26** |
| **total** | **50** |

Ningún criterio en rojo. Lo que queda por observar son los 21 que solo tienen
un test detrás, y los dos que miden ALTA-2 en vez de aprobarla.

## Cómo se actualiza

Cuando una ronda de validación cierre un criterio por producción o por
navegador, se mueve aquí **en el mismo commit** que el cambio que lo permitió.
Si no está escrito en el repo, no ocurrió: es la lección de las tres rondas que
tuvieron que reconstruirlo de memoria.
