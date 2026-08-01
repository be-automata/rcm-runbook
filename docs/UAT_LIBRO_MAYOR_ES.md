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
| `bloqueado` | Necesita un turno real del agente, y la cuenta del proveedor no tiene saldo. |

Un `test` verde dice que el código hace lo que su autor creía; no dice que el
sistema desplegado se comporte así delante de una persona. La distinción es la
diferencia entre este documento y una lista de deseos.

## Los 12 bloqueados por saldo

**1, 4, 8, 10, 23, 25, 26, 27, 29, 36, 40, 46.**

Eran once hasta que la validación encontró que el **46** —«el agente no
repregunta datos que el interesado ya dio»— tiene probado su mecanismo pero no
su enunciado: que no repregunte es conducta del modelo. Los cubre
`scripts/verificar_en_produccion.py` salvo el 26 (exige romper el entorno del
cliente), el 40 (pasó a revisión humana) y el 46.

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
| ✅ producción | 9 |
| ✅ navegador | 8 |
| ✅ solo test | 21 |
| ❌ | 0 |
| bloqueado por saldo | 12 |
| **total** | **50** |

## Cómo se actualiza

Cuando una ronda de validación cierre un criterio por producción o por
navegador, se mueve aquí **en el mismo commit** que el cambio que lo permitió.
Si no está escrito en el repo, no ocurrió: es la lección de las tres rondas que
tuvieron que reconstruirlo de memoria.
