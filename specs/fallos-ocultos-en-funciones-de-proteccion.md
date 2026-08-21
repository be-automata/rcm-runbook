# Un dispositivo de protección cuya falla no es oculta

> AUTOSUFICIENTE: ejecutable en una sesión nueva, por alguien que no
> participó de la conversación que la originó.

## 0. De dónde sale esto

Investigando por qué `test_llm_guided_session` fallaba distinto en cada corrida
apareció un hueco que no era del test. En dos de las tres corridas medidas el
análisis llegó a las seis compuertas **en verde** con el modo de falla del
presostato mal caracterizado, y el eval sólo se enteraba al final.

La causa: **ninguna compuerta ata las funciones de protección a efectos ocultos.**
`_gate_p3` (`src/rcm_runbook/engine/compliance.py`) sólo exige que los modos
creíbles tengan efectos y controles registrados. La única mención a
`FunctionKind.PROTECCION` en todo el módulo vive dentro de `validate_ja1011`, que
es **no bloqueante** y sólo comprueba que exista *alguna* función de protección —
no que sus modos estén marcados ocultos.

En RCM eso no es un detalle. Un modo que hace fallar una función de protección es
por definición un fallo oculto: es la rama entera del método —búsqueda de fallos,
FFI, prueba periódica del dispositivo—. Marcarlo evidente significa que **nunca
recibe política BF, nunca se le calcula el FFI, y el dispositivo de protección
nunca entra en un calendario de pruebas**. El entregable sale completo y con las
compuertas en verde, habiendo perdido en silencio la parte más crítica del
análisis.

## 1. Alcance

Que el motor no deje cerrar la fase 3 con un modo creíble colgado de una función
de protección cuyo efecto no declara ser oculto ni trae consecuencia.

### Entra
- Una invariante nueva en `_gate_p3`.
- El mensaje en español que el agente lee y usa para corregir **dentro de la
  conversación**, que es donde tiene el contexto.
- Tests unitarios sobre sesiones construidas a mano.

### NO entra (explícito)
- Corregir automáticamente los modos afectados. La compuerta señala; decide una
  persona (ver §2).
- Tocar `validate_ja1011`, que sigue siendo no bloqueante y una medición.
- El eval largo, que ya está rediseñado y **nombra** este defecto cuando ocurre
  (criterio `oculto_marcado` en `tests/evals/acta.py`).

## 2. La decisión que la compuerta NO debe tomar

**Evidencia del análisis real** (`tests/fixtures/uat_sesion_real.json`): de 13
modos creíbles colgados de las dos funciones de protección (`F-008`, `F-009`),
**6 tienen el efecto marcado como no oculto**:

```
FM-012  Válvula de retención bloqueada abierta          is_hidden=False safety=False
FM-048  Motor o sistema eléctrico incapaz de arrancar   is_hidden=False safety=False
FM-052  Degradación de la grasa de los rodamientos      is_hidden=False safety=False
FM-053  Aflojamiento de la base o pies cortos           is_hidden=False safety=False
FM-058  Desalineación entre bomba y motor              is_hidden=False safety=False
FM-060  Sentido de giro incorrecto                     is_hidden=False safety=False
```

Mirando los nombres, la mayoría **no parece un fallo de una función de
protección**: la degradación de la grasa, el aflojamiento de la base, la
desalineación y el sentido de giro son modos del tren de bombeo, no del
dispositivo protector — parecen colgados de la falla funcional equivocada.
`FM-012` (válvula de retención bloqueada abierta) y `FM-048` (el motor no puede
arrancar) sí parecen genuinamente ocultos: nadie los percibe hasta que se
necesita el arranque.

Por eso la compuerta **no debe asumir «márcalo oculto»**. Debe decir:

> El modo FM-052 cuelga de la función de protección F-009. O su efecto es oculto
> —la falla no se percibe en operación normal y hay que declarar la consecuencia—
> o el modo está colgando de la falla funcional que no le corresponde. Revíselo
> con el equipo.

Las dos salidas son correcciones que valen. Una compuerta que empuje a una sola
producirá modos marcados ocultos que no lo son, que es peor que el defecto que
viene a arreglar.

## 3. Criterios de aceptación

1. Una sesión con un modo creíble bajo función de protección y efecto
   `is_hidden=False` **no pasa la compuerta de fase 3**, y el mensaje ofrece las
   dos salidas.
2. Un modo bajo función de protección con `is_hidden=True` y al menos una
   consecuencia declarada **sí** pasa.
3. Un modo **no creíble** bajo función de protección no dispara la invariante (un
   modo descartado no necesita efecto).
4. `run_scripted_eval` sigue en verde sin tocar `pump_p101.yaml` — el escenario ya
   declara `is_hidden: true, safety: true` para FM-003.
5. `tests/export/test_golden.py` y el resto de fixtures siguen en verde. **Auditar
   antes**: buscar fixtures con funciones de protección cuyos modos no tengan
   efecto oculto, porque esas empezarán a fallar y hay que decidir una por una si
   el fixture estaba mal o si el caso es legítimo.
6. `tests/unit/test_sesion_real_como_ancla.py` documenta el conteo esperado tras
   la decisión sobre los 6 modos de Henry.

## 4. Notas de arquitectura

- Toca **sólo** `_gate_p3` en `src/rcm_runbook/engine/compliance.py`.
- El recorrido es `FailureMode.functional_failure_id → FunctionalFailure.function_id
  → Function.kind == FunctionKind.PROTECCION`.
- Respeta el patrón del módulo: la compuerta devuelve `list[str]` en español,
  accionable, y quien la lee es el agente. El comentario de `tools.py` sobre
  `advance_phase` documenta que decírselo en el punto de decisión bajó los
  rechazos inventados de 3/3 a 2/3 — la misma mecánica aplica aquí.

## 5. Tareas

1. [ ] Auditar fixtures y sesiones existentes: cuántas empezarían a fallar y por qué.
2. [ ] Implementar la invariante en `_gate_p3` con el mensaje de dos salidas.
3. [ ] Tests unitarios de los criterios 1-3.
4. [ ] Decidir con Henry los 6 modos del análisis real (oculto vs. mal colgado).
5. [ ] Re-sellar la sesión en Neon y actualizar el conteo del test de anclaje.

## Supuestos

- SUPUESTO: la invariante se aplica sólo a modos **creíbles**. Un modo descartado
  no tiene por qué tener efecto registrado, y la compuerta P3 ya lo trata así.
- SUPUESTO: exigir «al menos una consecuencia declarada» no añade fricción real,
  porque el modelo `Effect` ya lo valida en `at_least_one_consequence_flag`. Lo
  que la invariante añade es la exigencia de que el efecto **exista y sea oculto**.

## Hallazgo relacionado, abierto

En el análisis real, `FM-014` y `FM-015` tienen la búsqueda de fallas calculada
cada **526 h** y la tarea agendada `Mensual` (**730 h**): el dispositivo de
protección se prueba menos a menudo de lo que exige su propio cálculo, sobre los
dos únicos modos ocultos que llevan firma. El motor **ya lo detecta** —sale como
bloqueador de clase incoherencia, ver `bloqueadores_por_clase`— así que no hace
falta código nuevo; hace falta que alguien lo corrija en el análisis.
