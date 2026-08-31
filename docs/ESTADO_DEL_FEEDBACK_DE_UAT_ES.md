# Los cinco hallazgos del UAT — dónde está cada uno

Ronda del 09–11 ago 2026 con el interesado (ingeniero de mantenimiento, tester y
product owner), sobre la sesión `demo-7aa88eb4-0889-4a91-b7b5-6a5cd4a3edc9`.

Este documento existe porque la pregunta «¿queda algo pendiente?» costaba media
hora de arqueología entre specs, PRs y casillas desactualizadas. Se actualiza
cuando cambie el estado de un hallazgo, no cuando entre un PR.

| # | Hallazgo | Estado |
|---|---|---|
| 1 | Los identificadores `FF-`/`FM-` no llegan al Excel | **Cerrado** — PR #1 |
| 2 | Modos sin clasificar evidente/oculta, sin razón visible | **Cerrado** — PR #1 |
| 3 | Informe con análisis costo-beneficio por actividad | **No se hará (decidido)** |
| 4 | Glosario de terminología; usar «fallo» en vez de «falla» | **Cerrado, con un matiz** |
| 5 | Colaboración asíncrona por correo | **No se hará (decidido)** |

## 1 y 2 — cerrados

`specs/trazabilidad-y-clasificacion-en-el-excel.md`, 9 de 9 tareas. El `FM-` va en
la columna A de AMEF y PLAN, el `FF-` dentro de su celda, y ninguna fila queda sin
clasificar en silencio: antes eran 28 de 60 mudas. Verificado en producción
(libro mayor de UAT, ronda 47).

## 4 — cerrado, con un matiz que conviene saber

`specs/glosario-y-terminologia.md`, 8 de 8. El agente habla en registro de España
y usa el eje **fallo** (evento) / **avería** (estado) de la UNE-EN 13306; nunca
dice «avería oculta», que sería un error técnico y no sólo de registro.

**El matiz:** el Excel sigue diciendo «Falla Funcional», «Modo de Falla» y
«Operar hasta la falla». No es un olvido: son cadenas **congeladas** contra el
libro de referencia del cliente, protegidas por dos golden tests. El agente las
**cita entrecomilladas, no las traduce** — si las tradujera, el ingeniero que
busca una columna en su propia plantilla no la encontraría.

Cambiarlas es posible, pero es un cambio del libro del cliente y necesita su
propia decisión. Lo mismo aplica a la etiqueta `Bi-Anual` del menú.

## 3 y 5 — decididos fuera de alcance, nunca construidos

Ninguno de los dos se empezó, y no por descuido: quedaron declarados fuera de
alcance en `specs/trazabilidad-y-clasificacion-en-el-excel.md` y en
`specs/veracidad-de-lo-que-el-agente-afirma.md`.

- **3, informe costo-beneficio por actividad.** Es una feature de producto, no un
  defecto. Requiere datos que hoy no se recogen (coste de la tarea, coste de la
  falla, horas de parada).
- **5, colaboración asíncrona por correo.** Es multiusuario: notificaciones,
  identidad y permisos. Hoy la demo no tiene ninguno de los tres.

Si alguno vuelve a la mesa, entra como feature con su spec, no como corrección.

## Tres cosas de la llamada que la lista de cinco no recogió

Releyendo la transcripción del 11-ago contra los cinco hallazgos, aparecen tres
peticiones que se perdieron al resumir. No estaban descartadas: estaban ausentes.

### El informe exportable, que no es lo mismo que el costo-beneficio

Textual: *«lo que sí hay que añadirle es lo de la exportación, **que elabore un
informe para exportar**… quiero un archivo Word. Se lo pedí y me lo dio, pero
**debería ser parte del final del trabajo**. Y darle un modelo de cómo debería
estructurarlo».* Y **después**, como algo que él acostumbra a incluir dentro de
ese informe: *«yo acostumbro… un análisis de costo beneficio»*.

Son dos cosas: el informe es el continente, el costo-beneficio es una sección.
La lista de cinco las fundió en «Informe con análisis costo-beneficio por
actividad», y la spec excluyó el conjunto razonando sólo sobre el
costo-beneficio —que sí necesita datos que hoy no se recogen—. **El informe se
descartó por arrastre.**

Y es mucho más barato de lo que esa exclusión sugiere: el agente **ya lo produce
si se lo piden** («se lo pedí y me lo dio»). Lo que falta es que forme parte del
cierre y que tenga una plantilla. Henry se ofreció a mandar la suya.

### El agente habla en sintaxis interna

Textual: *«a veces una instrucción de tal cosa **igual a true**»*. No es fuga de
inglés —eso es el hallazgo 4— sino fuga de **implementación**: el agente le
enseña al usuario nombres de parámetro.

La causa está a la vista en `instructions_es.py`, que usa `draft=True`,
`reemplazar=True` y `es_busqueda_de_fallas=True` en su propio texto y nunca dice
que eso no se le cuenta al interesado. Henry lo restó importancia («aquí todo el
mundo habla inglés»), pero un ingeniero de mantenimiento no tiene por qué saber
qué es `es_busqueda_de_fallas`.

### Los códigos se inventan en vez de consultarse

Textual: *«los códigos se van creando nuevo, parece que **para que utilice uno
existente hay que explicarle bien**»*.

Hay dos herramientas para esto —`lookup_iso14224` y `explain_iso_code`— y
**ninguna se nombra en el prompt**, así que nada le dice al agente que consulte
antes de asignar. Observado tres veces de forma independiente: Henry en la
llamada, las corridas del eval (inventó `BA3113`, `BR1140`, `ME4340`, que son
códigos de *equipo* y no de modo de fallo) y el criterio [29] del verificador de
producción, que sigue marcado como «requiere ojo humano».

La validación determinista rechaza los inventados, así que no llegan al
entregable — pero el interesado ve el intento y tiene que corregirlo a mano.

## Dos cosas que dependen de Henry, comprometidas en la llamada

| Entrega | Textual |
|---|---|
| Excel de referencia actualizado | *«te voy a actualizar el Excel para que te lo metas como yo quiero»* |
| Plantilla del informe | *«te voy a mandar el informe también para que se lo incluya»* |

Sin la segunda, el informe exportable no se puede cerrar: falta el modelo de
estructura que él mismo pidió que se le diera al agente.

## Lo que salió después, y no venía en la lista de cinco

| Tema | Estado |
|---|---|
| 28 modos de falla duplicados | `specs/supersesion-de-modos-de-falla.md` — **abierto**; 4 pares necesitan que el interesado arbitre |
| 6 modos en funciones de protección sin marcar ocultos | `specs/fallos-ocultos-en-funciones-de-proteccion.md` — **abierto**; necesita su criterio |
| 2 pruebas más espaciadas que su propio intervalo (FM-014, FM-015) | **abierto** — el motor lo detecta; falta corregir el análisis |
| Manifiesto de lo que el agente afirma del entregable | `specs/veracidad-de-lo-que-el-agente-afirma.md`, tareas 4-8 — **abierto** |

Las tres primeras dependen del criterio del interesado y no de código. La cuarta
es trabajo de desarrollo pendiente.
