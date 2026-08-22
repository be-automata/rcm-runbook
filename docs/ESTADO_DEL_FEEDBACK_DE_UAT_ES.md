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

## Lo que salió después, y no venía en la lista de cinco

| Tema | Estado |
|---|---|
| 28 modos de falla duplicados | `specs/supersesion-de-modos-de-falla.md` — **abierto**; 4 pares necesitan que el interesado arbitre |
| 6 modos en funciones de protección sin marcar ocultos | `specs/fallos-ocultos-en-funciones-de-proteccion.md` — **abierto**; necesita su criterio |
| 2 pruebas más espaciadas que su propio intervalo (FM-014, FM-015) | **abierto** — el motor lo detecta; falta corregir el análisis |
| Manifiesto de lo que el agente afirma del entregable | `specs/veracidad-de-lo-que-el-agente-afirma.md`, tareas 4-8 — **abierto** |

Las tres primeras dependen del criterio del interesado y no de código. La cuarta
es trabajo de desarrollo pendiente.
