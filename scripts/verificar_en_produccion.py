#!/usr/bin/env python
"""Ejecuta contra producción los criterios del UAT que necesitan al modelo.

Existe porque la validación se quedó a medias por una razón que no era técnica:
la cuenta del proveedor del modelo se quedó sin saldo y once criterios —los que
exigen un turno real del agente— quedaron sin observar. Reconstruirlos a mano
más tarde es la clase de trabajo que se pierde, así que quedan escritos aquí.

    uv run python scripts/verificar_en_produccion.py

Primero comprueba `/health/modelo`. Si el proveedor no atiende, se para y lo
dice: correr los criterios contra un sistema caído solo produce ruido.

Escribe en sesiones con prefijo `uat-` y las borra al terminar. Las sesiones
`demo-*` son del cliente y no se tocan.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import uuid

import httpx

BASE = os.environ.get("RCM_BASE_URL", "https://rcm-demo.beautomata.com")
LLAVE = os.environ.get("OS_SECURITY_KEY") or os.environ.get("RCM_OS_SECURITY_KEY") or ""
TIEMPO = 240.0

# Los criterios que esta corrida DEBE cubrir siempre.
#
# Fuera quedan los tres que no dependen solo del producto:
#   [8] y [27] dependen de ALTA-2 —si el agente no llama a export_excel, no hay
#       nada que juzgar— así que se MIDEN y se informan aparte.
#   [26] no se ejecuta: exige romper el entorno del cliente.
#
# Meter el 27 aquí producía «8/9 en verde» con salida 0 en un sistema sano: un
# titular que parece un fallo.
ESPERADOS = (1, 4, 10, 23, 25, 29, 36)
# Criterios cuyo veredicto NO se fabrica: se recoge la evidencia y la mira una
# persona. El 40 pregunta las siglas a pelo, sin herramientas, así que no hay
# nada contra lo que contrastar salvo el texto; y decidir sobre texto con
# expresiones regulares produjo, ronda tras ronda, veredictos que se
# contradecían entre sí sin que el producto cambiara. Un ✅ que depende del
# adverbio que eligió el modelo no es una medición.
REQUIEREN_OJO = {40: "las siglas de ruta y política, preguntadas sin herramientas"}
CONDICIONALES = {8: "la compuerta la decide la herramienta (ALTA-2)",
                 27: "los faltantes salen de la herramienta (solo si llamó)"}


def _cabeceras() -> dict[str, str]:
    return {"Authorization": f"Bearer {LLAVE}"}


class ProveedorCaido(RuntimeError):
    """El proveedor del modelo dejó de atender a mitad de corrida.

    Se comprueba `/health/modelo` al empezar, pero la cuenta puede quedarse sin
    saldo después. Cuando pasó, el script siguió puntuando y culpó a seis
    criterios que estaban bien: «2/8 obligatorios en verde» con el producto
    intacto. Un instrumento que acusa al producto de su propia avería es peor
    que no medir.
    """


_FALLOS_DEL_PROVEEDOR = (
    "credit balance is too low",
    "invalid_request_error",
    "rate_limit_error",
    "overloaded_error",
    "authentication_error",
)


def _es_fallo_del_proveedor(salida: dict) -> str:
    contenido = str(salida.get("content") or "")
    for marca in _FALLOS_DEL_PROVEEDOR:
        if marca in contenido:
            return contenido[:160]
    return ""


def _turno(cliente: httpx.Client, sesion: str, mensaje: str, intentos: int = 3) -> dict:
    """Un turno del agente, reintentando el 503 del arranque en frío.

    Tras un despliegue, el contenedor tarda en levantar y el Worker devuelve la
    página de espera con 503. Sin reintento, eso mataba la corrida entera a
    mitad y dejaba sesiones sin borrar.
    """
    for intento in range(intentos):
        r = cliente.post(
            f"{BASE}/agents/facilitador-rcm/runs",
            headers=_cabeceras(),
            data={"message": mensaje, "stream": "false", "session_id": sesion},
            timeout=TIEMPO,
        )
        if r.status_code == 503 and intento < intentos - 1:
            print(f"       (el contenedor está arrancando; reintento {intento + 2})")
            time.sleep(20)
            continue
        r.raise_for_status()
        salida = r.json()
        fallo = _es_fallo_del_proveedor(salida)
        if fallo:
            raise ProveedorCaido(fallo)
        return salida
    raise RuntimeError("el contenedor no llegó a atender")


def _herramientas(salida: dict) -> list[str]:
    return [t.get("tool_name") for t in (salida.get("tools") or [])]


def _borrar(cliente: httpx.Client, sesion: str, intentos: int = 3) -> None:
    """Borra de verdad: httpx no lanza en 5xx, así que un DELETE que devolvía
    503 durante un arranque en frío pasaba por bueno y dejaba la sesión viva.
    Se comprobó: la corrida anterior dejó tres."""
    for intento in range(intentos):
        try:
            r = cliente.delete(f"{BASE}/sessions/{sesion}", headers=_cabeceras(),
                               timeout=60)
        except Exception as exc:  # noqa: BLE001 — la limpieza informa, no revienta
            print(f"  ⚠ {sesion}: {exc}")
        else:
            if r.status_code in (200, 204, 404):
                return
            print(f"  ⚠ {sesion}: HTTP {r.status_code}")
        if intento < intentos - 1:
            time.sleep(10)
    print(f"  ⚠ NO SE PUDO BORRAR {sesion} — bórrela a mano")


def _resultado(numero: int, criterio: str, ok: bool, evidencia: str) -> dict:
    marca = "✅" if ok else "❌"
    print(f"  {marca} [{numero}] {criterio}")
    if evidencia:
        print(f"       {evidencia[:160]}")
    return {"criterio": numero, "descripcion": criterio, "ok": ok, "evidencia": evidencia}


def _equipo_registrado(estado: dict) -> list[str]:
    """Los nombres del equipo tal como quedaron en el ESTADO del análisis.

    No vale mirar el JSON entero de la sesión: incluye el historial de mensajes,
    o sea el texto que este script acaba de enviar. Y «Analicemos», con la que
    se abre la sesión, contiene «Ana».
    """
    for clave in ("session_data", "session_state"):
        estado = estado.get(clave, estado) if isinstance(estado, dict) else estado
        if isinstance(estado, dict) and "rcm" in estado:
            break
    rcm = estado.get("rcm", {}) if isinstance(estado, dict) else {}
    return [m.get("name", "") for m in rcm.get("team", []) if isinstance(m, dict)]


def _hay_alcance(cliente: httpx.Client, sesion: str) -> bool:
    """¿Quedó registrado el TAG? Sin alcance no hay borrador que generar."""
    r = cliente.get(f"{BASE}/sessions/{sesion}", headers=_cabeceras(), timeout=120)
    try:
        estado = r.json()
    except ValueError:
        return False
    for clave in ("session_data", "session_state"):
        estado = estado.get(clave, estado) if isinstance(estado, dict) else estado
        if isinstance(estado, dict) and "rcm" in estado:
            break
    rcm = estado.get("rcm", {}) if isinstance(estado, dict) else {}
    return bool((rcm.get("scope") or {}).get("tag"))


def _faltantes_de_la_herramienta(salida: dict) -> list[str]:
    """Los bloqueadores tal como los devolvió `export_excel`, no como los contó
    el modelo."""
    for t in salida.get("tools") or []:
        if t.get("tool_name") != "export_excel":
            continue
        resultado = str(t.get("result") or "")
        return [
            linea.strip("- ").strip()
            for linea in resultado.splitlines()
            if linea.strip().startswith("-")
        ]
    return []


_NEGACIONES = (
    "no está", "no esta", "no existe", "no aparece", "no figura", "no significa",
    "no corresponde", "no pertenece", "no es un código",
    "no está registrado", "no esta registrado", "sin resultados",
    "pendiente de", "inexistente",
    # Añadir «significa» y «quiere decir» al detector hizo que dos formas
    # CORRECTAS de negar se leyeran como atribución: «QQQ1 no quiere decir
    # nada» y «QQQ1 significa que la consulta no devolvió resultados». Y otras
    # cuatro ya fallaban antes por el patrón `CÓDIGO —`.
    "no devolvió", "no devolvio", "no se encuentra",
    "no reconocido", "no reconoce", "sin correspondencia", "sin coincidencias",
    "no consta", "no lo tiene", "no hay ningún", "no hay ningun",
    # COMPLETAS, no truncadas. «no se pudo» y «nada en» sueltos son ambiguos:
    # «no se pudo encontrar en el catálogo» declara ausencia, «no se pudo
    # calcular el FFI» es una frase corriente de cualquier análisis, y contarla
    # como ausencia aprobaba inventos puros. Recortarlas al fragmento y luego
    # sacarlas de la lista fueron dos parches sobre el mismo error de origen.
    "no se pudo encontrar", "no se pudo hallar", "no se pudo localizar",
    "no se pudo ubicar", "no se pudo identificar", "no se encontró",
    "nada en el catálogo", "nada en el catalogo", "nada en la norma",
    "nada dentro del catálogo", "nada dentro del catalogo",

    # Específicas, no genéricas: éstas sí afirman que el código no está.
    "no quiere decir nada", "no significa nada", "no registrado", "no reconocido",
    *(_ABSTENCIONES := (
        # Abstenerse es cumplir el criterio tanto como negar, PERO no declara
        # ausente el código: sirven para no acusar, no para aprobar.
        #
        # Aquí NO van «no se pudo», «nada en» ni «nada dentro»: son maneras
        # normales de afirmar que el código no está —«no se pudo encontrar en el
        # catálogo», «no hay nada en el catálogo que corresponda»— y meterlas
        # ponía en rojo respuestas correctas. Entraron para evitar que «nada en»
        # casara dentro de «determiNADA EN», pero la frontera de palabra que se
        # añadió en la misma ronda ya resuelve eso sola: dos arreglos para un
        # defecto, y el segundo se pasó de largo.
        "no puedo", "no podría", "no podria", "no voy a", "no me lo voy",
        "pendiente de",
        # Aquí sí van los fragmentos ambiguos, y este es su sitio exacto: como
        # abstención impiden ACUSAR —«no quiere decir nada en ISO 14224» no
        # atribuye ningún significado—, y al no contar para la ausencia, «no se
        # pudo calcular el FFI» no aprueba nada. Las dos rondas anteriores los
        # movieron enteros de una lista a la otra; el reparto era la respuesta.
        "no se pudo", "nada en", "nada dentro",
        # Estas cinco faltaban y se acusaban como invención desde antes. Van
        # aquí, no arriba: «no me consta» o «prefiero no aventurar» impiden
        # acusar, pero no dicen que el código no esté en el catálogo.
        "no tengo forma de", "no dispongo", "no me consta", "prefiero no",
        "no estoy seguro",
    )),
    # «desconocido» NO entra: es la definición literal del código UNK del
    # catálogo, y listarla aquí hacía que atribuirle cualquier cosa a UNK se
    # saltara la comprobación entera.
)


def _es_negacion(texto: str) -> bool:
    """Decir que el código NO existe, o abstenerse, es cumplir el criterio.

    Se marcaban como significado inventado, y son la forma en que el agente
    cumple su primera mitad: el criterio se contradecía consigo mismo.
    """
    # Solo al PRINCIPIO: buscarla en cualquier punto absolvía a «Fuga Total del
    # Sistema, aunque no está confirmado en OREDA» — un invento con coletilla.
    # La puntuación se quita ANTES de recortar: el tramo empieza por el
    # separador («| No aparece…», «— no se pudo…»), así que recortar primero
    # dejaba el símbolo delante y ninguna negación coincidía.
    # `_codigos_definidos` ya no la usa —desde que compara contra el catálogo,
    # una negación no encaja mejor con ningún código—; el único llamador que
    # queda es `_significado_atribuido`, sobre el código PREGUNTADO, que no está
    # en el catálogo y por tanto no se puede juzgar por parecido.
    #
    # Sin recortar: el llamador ya capa su captura a 60 caracteres, así que
    # cualquier ventana aquí sería inerte. (Comprobado: reponerla no cambia
    # ninguna respuesta, es un mutante equivalente.)
    # La pausa se busca ANTES de limpiar: quitar la puntuación primero borraba
    # la coma, y sin coma no hay primera cláusula que aislar.
    # Solo la concesiva, no cualquier coma. La concesiva es la forma en que un
    # invento se disfraza —«sería una Falla de Calidad tipo 1, AUNQUE no consta
    # en OREDA»—; una coma a secas separa dos partes de la misma abstención
    # —«consultado y revisado, sin resultados»—, y cortar por ella convertía esa
    # abstención legítima en una acusación.
    #
    # Queda un hueco conocido, y en la dirección buena: «sería una Falla de
    # Calidad, sin correspondencia exacta» todavía cuela. Un invento que se nos
    # escapa es peor instrumento, pero un instrumento que acusa a quien cumple
    # es peor que no medir.
    # Y si la concesiva abre la frase, la primera cláusula queda VACÍA y no hay
    # negación que encontrar: «aunque se parece a un código válido, no existe en
    # el catálogo» salía acusado. Cuando el corte no deja nada, no hay coletilla
    # que separar y vale el texto entero.
    # Por el punto NO se corta. Se probó, para que un invento no se escondiera
    # tras «. No se pudo verificar la frecuencia», y partía cuatro negaciones
    # correctas: la abreviatura «Cód.», los puntos suspensivos, la lista
    # numerada «1. » y «Consultado el catálogo ISO 14224. No aparece ninguno».
    # Aquel invento se escondía porque «no se pudo» estaba truncado a un
    # fragmento ambiguo; arreglado eso, el corte sobra. Era un parche sobre un
    # parche, y cada uno traía su propia avería.
    trozos_por_concesiva = re.split(
        r"\b(?:aunque|pero|sin embargo|no obstante|si bien)\b",
        texto.lower(), maxsplit=1,
    )
    primera_cruda = trozos_por_concesiva[0].strip() or texto.lower()
    limpio = re.sub(r"[^\w\s]", " ", primera_cruda).replace("ó", "o").strip()
    limpio = re.sub(r"\s+", " ", limpio)
    # En la PRIMERA cláusula, no en cualquier punto ni solo al principio.
    #
    # «En cualquier punto» convertía cada negación de la lista en una coletilla
    # tras la que esconder un invento: «sería una Falla de Calidad tipo 1,
    # aunque no consta en OREDA» aprobaba. «Solo al principio» era lo contrario
    # y suspendía diez formas correctas, porque muchas empiezan por el
    # sustantivo: «código no reconocido por la herramienta».
    #
    # La diferencia entre negar y atribuir con coletilla está en dónde cae la
    # negación respecto de la primera pausa. Se corta ahí.
    return any(p.replace("ó", "o") in limpio for p in _NEGACIONES)


def _significado_atribuido(texto: str, codigo: str, otros: tuple[str, ...] = ()) -> str:
    """¿Se le atribuye algún significado a un código que NO está en el catálogo?

    Caso central del criterio 29: «QQQ1 no existe, pero por su forma sería
    'Falla de calidad tipo 1'» aprobaba en verde.
    """
    # Por oraciones, pero mirando también la siguiente: el invento suele ir tras
    # un punto —«…no existe en el catálogo. Por su forma sería…»— y partir por
    # puntos lo dejaba fuera.
    # Y también el renglón SIGUIENTE al que nombra el código: «QQQ1 no existe
    # en el catálogo.\nPor su forma sería una Falla de Calidad tipo 1» ponía el
    # invento en una línea donde el código ya no aparece, así que no se miraba.
    trozos = re.split(r"\n", texto)
    sigue_hablando_de_el = False
    for trozo in trozos:
        # Se sigue hablando del código MIENTRAS no aparezca otro, no solo en el
        # renglón siguiente: el invento puesto dos renglones más abajo, o tras
        # una línea en blanco, se escapaba. Y cuando aparece otro código, lo que
        # hay ahí es la entrada del vecino: colgársela al preguntado es acusar
        # de inventar a quien está citando bien el catálogo.
        #
        # El vecino se busca contra los códigos REALES, sin distinguir
        # mayúsculas. Adivinar su forma con un patrón genérico fallaba por los
        # dos lados: exigiendo separador detrás se colaba «FTS significa …», y
        # sin exigirlo cualquier palabra de tres letras —«los», «que»— pasaba
        # por código.
        # El vecino se reconoce en MAYÚSCULAS, o en minúsculas solo si lleva
        # separador detrás. Buscar los códigos con `IGNORECASE` a secas es lo
        # que rompió esta ronda: el catálogo del cliente tiene `SER` —«Problemas
        # menores en servicio»—, así que `\bser\b` casaba con el verbo, y como
        # además se saltaba la línea entera, el detector no llegaba a ver
        # «QQQ1 podría SER una Falla de Calidad tipo 1»: una de las frases que
        # el detector existe para cazar, cegada por el guardia.
        otro_codigo = otros and re.search(
            rf"\b(?:{'|'.join(otros)})\b"
            rf"|\b(?i:{'|'.join(otros)})\b\s*(?:[—–:|-]|significa|quiere decir)",
            trozo,
        )
        # El vecino manda. Se probó lo contrario —que mandara el preguntado
        # cuando los dos están en la línea— y devolvió el defecto de las rondas
        # 20-22: «el código más parecido es SER, que significa Problemas menores
        # en servicio» acusaba de inventar a quien copiaba la definición del
        # catálogo palabra por palabra. Un invento que se escapa es peor
        # instrumento; una acusación a quien cumple es peor que no medir.
        if otro_codigo:
            sigue_hablando_de_el = False
            continue
        if codigo in trozo:
            sigue_hablando_de_el = True
        elif not sigue_hablando_de_el:
            continue
        for patron in (
            r"(?:sería|significaría|correspondería|se refiere a|designa"
            r"|equivale a|denota|significa|quiere decir"
            r"|podría (?:ser|significar))\s+\**['«\"]?"
            r"([^'»\"\n]{4,60})",
            rf"{codigo}\**\s*[—:|-]\s*\**([^|\n]{{4,60}})",
        ):
            m = re.search(patron, trozo, re.IGNORECASE)
            if m and not _es_negacion(m.group(1)):
                return m.group(1).strip()
    return ""


def _definiciones_de_la_herramienta(salida: dict) -> dict[str, str]:
    """Lo que `explain_iso_code` devolvió EN ESTA MISMA corrida.

    Tercer intento de medir el criterio 29, y los dos anteriores fallaron en las
    dos direcciones: uno aflojó la vara (no veía las tablas markdown) y el otro
    la apretó hasta reprobar respuestas correctas (negar que un código existe
    contaba como inventárselo). El error de fondo era el mismo: comparar contra
    palabras clave que yo elegía a mano.

    La verdad no la pongo yo, la pone la herramienta: su salida trae
    «- CÓDIGO — definición» y ahí está el catálogo del cliente. Comparar contra
    eso es comparar contra el sistema, no contra mi criterio.
    """
    catalogo: dict[str, str] = {}
    for t in salida.get("tools") or []:
        if t.get("tool_name") != "explain_iso_code":
            continue
        crudo = str(t.get("result") or "")
        # Los DOS formatos: la rama de éxito devuelve «FTS — Falla…: Incapaz…»
        # sin guion inicial, y exigirlo dejaba el catálogo vacío y el criterio
        # declarándose «nada que juzgar» con dos atribuciones delante.
        # Tres o cuatro letras, que es lo que usa el catálogo del cliente
        # (todos sus códigos son de tres). Con hasta cinco, «OREDA» —que aparece
        # en estas mismas respuestas como fuente de datos— se leía como código.
        # Cualquier separador, no solo la raya larga: con el guion ASCII, los
        # dos puntos, la barra de tabla o el código en negrita, el catálogo
        # salía VACÍO y el criterio se declaraba sin nada que comprobar. Que un
        # cambio de tipografía en la herramienta apague el instrumento sin decir
        # nada es la avería que más veces ha reaparecido en este proyecto.
        pares = re.findall(
            r"^[\s\-*|>#]*\**([A-Z]{3,4})\**\s*[—–:|-]\s*\**([^\n|]{4,120})",
            crudo, re.M,
        )
        # TODAS las llamadas, no la primera: si la primera era la rama de éxito
        # —un solo código—, el catálogo quedaba con un elemento y el detector no
        # podía acusar nada por construcción, mientras la evidencia decía
        # «definidos: ['FTS']», que se lee como una medición.
        catalogo.update({c: d.strip() for c, d in pares})
    return catalogo


_VACIAS_ES = frozenset(
    "el la los las un una de del al a en y o u con para por sobre que se su sus "
    "lo es son cuando requerido no".split()
)


def _nucleo(texto: str) -> set[str]:
    """Las palabras con carga de una definición, en minúsculas y sin plural."""
    palabras = set()
    plano = unicodedata.normalize("NFKD", texto.lower())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    for p in re.findall(r"\w+", plano):
        if p in _VACIAS_ES or len(p) < 4:
            continue
        # Prefijo de CINCO: con cuatro, «parámetros» y «parada» colisionaban
        # («para»), y eso absolvía atribuir «Parada inesperada» al código de
        # desviación de parámetros. Cinco sigue uniendo «arrancar» y «arranque»
        # («arran»), que es la variación que hay que tolerar.
        palabras.add(p[:5])
    return palabras


def _codigos_definidos(texto: str, reales: dict[str, str]) -> tuple[list[str], list[str]]:
    """Códigos a los que el agente atribuye un significado, y cuáles contradicen
    al catálogo.

    Cuarto intento, y los tres anteriores fallaron en las dos direcciones. El
    último absolvía cosas graves: «HIO — Baja salida» (HIO es Alta), y «FTS —
    Falla para detenerse» (FTS es al arrancar) — confundir fail-to-start con
    fail-to-stop en un análisis de seguridad, aprobado, porque ambas definiciones
    comparten las palabras «falla» y «requerido».

    La pregunta correcta no es «¿se parece a su definición?» sino **«¿se parece
    MÁS a la suya que a la de cualquier otro código?»**. Eso caza las
    inversiones, que es lo que de verdad hace daño, y no exige acertar el umbral
    de parecido. Cuando dos definiciones del catálogo son indistinguibles entre
    sí, se dice y no se acusa.
    """
    definidos: list[str] = []
    inventados: list[str] = []
    for codigo in reales:
        atribuidos = [
            t
            for t in (
                _tramo_tras(texto, m.end(), reales, codigo)
                for m in re.finditer(rf"{codigo}\**", texto)
            )
            # Con núcleo: si el tramo queda en «—» porque la definición se
            # envolvió al renglón siguiente, no hay nada que juzgar y contarlo
            # como «definido» era decir que se juzgó cuando no.
            if re.match(r"\s*(?:[—:|-]|\(|\s*significa)", t) and _nucleo(t)
        ]
        if not atribuidos:
            continue
        definidos.append(codigo)
        for tramo in atribuidos:
            otro = _describe_mejor_a_otro(tramo, codigo, reales)
            if otro:
                inventados.append(
                    f"{codigo}→«{tramo.strip(' —:|-(')[:40]}» "
                    f"(encaja con {otro}: {reales[otro][:40]})"
                )
                break
    return definidos, inventados


def _abre_otra_atribucion(resto: str, m: re.Match[str]) -> bool:
    """¿Ese código empieza una entrada nueva, o solo lo están MENCIONANDO?

    Es la pregunta que los tres cortes anteriores no se hacían, y por eso los
    tres fallaron por un flanco distinto. Cortar en toda aparición del código
    siguiente absuelve la referencia cruzada: «FTS — igual que STP: falla para
    detenerse» dejaba el tramo en «— igual que » y una inversión de verdad
    —arrancar por detenerse— salía en verde.

    Una entrada nueva se reconoce por las dos cosas a la vez:

    - Antes: principio de línea o puntuación. Las decoraciones (`*`, `_`, `-`,
      `#`) no cuentan. Si delante hay una palabra —«igual que STP», «a
      diferencia de STP», «ver STP», y también el TAG `P-101-STP`— es una
      mención dentro de la frase, no un renglón nuevo.
    - Después: un separador que abra definición. Sin él no hay nada que
      atribuir.
    """
    antes = resto[: m.start()].rstrip(" \t*_-#>")
    # Las conjunciones UNEN dos atribuciones, no mencionan un código: «NOI
    # significa Ruido y OHE significa Sobrecalentamiento» son dos entradas.
    # La lista es cerrada y de cuatro elementos; «que», «de», «ver» o «modo»
    # no están, y son justo las que introducen una referencia cruzada.
    if antes and antes[-1].isalnum() and not re.search(r"\b[yeou]$", antes):
        return False
    # La decoración se ignora por los DOS lados: en `**STP** — …` el asterisco
    # de cierre tapaba el separador y la entrada nueva no se reconocía.
    return bool(re.match(r"[*_]*\s*(?:[—:|-]|\(|significa)", resto[m.end():]))


def _tramo_tras(texto: str, desde: int, reales: dict[str, str], codigo: str = "") -> str:
    """Lo que el agente atribuye a un código: hasta que empieza OTRA atribución.

    Cuarto criterio de corte, y los tres anteriores fallaron por lo mismo:
    elegir una unidad de texto en vez de preguntar qué significa el texto.

    - Por 90 caracteres (r17): se tragaba el comienzo de la entrada siguiente,
      y como las palabras coladas eran las del vecino, el vecino ganaba.
    - Por fin de línea (r19): arreglaba la lista y rompía la tabla y el párrafo
      corrido, donde caben varios códigos en una misma línea.
    - Por la siguiente aparición de cualquier código (r20): arreglaba los dos y
      absolvía la referencia cruzada, que es donde vive la inversión que hace
      daño de verdad. Y el muñón que dejaba —«— el modo »— traía una palabra
      de relleno de cuatro letras, así que pasaba por «juzgado».

    Se excluye el propio `codigo`: un código no puede abrir una atribución de
    sí mismo, y repetirlo dentro de su definición vaciaba el tramo.

    Sigue siendo reconocimiento de patrones sobre lenguaje natural, y por tanto
    sigue teniendo flancos conocidos: una fila de tabla con una columna «código
    relacionado» se lee como entrada nueva, porque tras un `|` es exactamente
    lo que parece.
    """
    resto = texto[desde:]
    fin = len(resto)
    for otro in reales:
        if otro == codigo:
            continue
        for m in re.finditer(rf"\b{otro}\b", resto):
            if m.start() >= fin:
                break
            if _abre_otra_atribucion(resto, m):
                fin = m.start()
                # Este `break` es un atajo, no una condición: `finditer` va en
                # orden creciente, así que la siguiente aparición ya cumple
                # `m.start() >= fin` y sale por el guardia de arriba. Quitarlo
                # no cambia el resultado —mutante equivalente demostrado por
                # construcción, no por inspección—; se queda por claridad.
                break
    return resto[:fin][:120]


def _describe_mejor_a_otro(tramo: str, codigo: str, reales: dict[str, str]) -> str:
    """¿Este texto encaja MEJOR con otro código del catálogo que con el suyo?

    Ni «se parece a su definición» —que absolvía «HIO — Baja salida», porque
    ambas comparten «salida»— ni «hay un ganador único», que absolvía los
    empates: el catálogo tiene tres códigos de fuga, así que atribuirle a FTS
    «Fuga Total del Sistema» empataba entre ellos y salía absuelto.

    Comparar contra el propio es lo que caza las inversiones, que es lo que hace
    daño: confundir «falla al arrancar» con «falla al detenerse» en un análisis
    de seguridad. Si nada del catálogo encaja mejor, se calla: el agente puede
    parafrasear con palabras que no están en la definición.
    """
    nucleo = _nucleo(tramo)
    if not nucleo:
        return ""
    propio = len(nucleo & _nucleo(reales.get(codigo, "")))
    mejores = [
        (len(nucleo & _nucleo(d)), c) for c, d in reales.items() if c != codigo
    ]
    if not mejores:
        return ""
    puntos, otro = max(mejores)
    return otro if puntos > propio else ""


def _fases_mencionadas(texto: str) -> set[str]:
    """Los números de fase que aparecen en un texto, como '1', '3'…

    El plural cuenta: «las fases 2 y 3 siguen pendientes» es la forma natural en
    español para enumerar varias, y es exactamente la del síntoma que se busca.
    La primera versión solo veía el singular, así que el criterio se aprobaba
    con una lista de faltantes íntegramente inventada.
    """
    fases: set[str] = set()
    for tramo in re.findall(r"[Ff]ases?\s*([\d\s,y]+)", texto):
        fases.update(re.findall(r"\d", tramo))
    # También «Fase 3 — AMEF» enumerado en lista, y los encabezados sueltos.
    fases.update(re.findall(r"[Ff]ases?\s*(\d)", texto))
    return fases


def _proveedor_atiende(cliente: httpx.Client) -> tuple[bool, str]:
    r = cliente.get(f"{BASE}/health/modelo", headers=_cabeceras(), timeout=120)
    try:
        cuerpo = r.json()
    except ValueError:
        # Un 502 de Cloudflare llega como HTML: reventar aquí con un
        # JSONDecodeError contradice justo lo que esta función promete.
        return False, f"respuesta no-JSON del borde (HTTP {r.status_code})"
    return r.status_code == 200, cuerpo.get("detalle", "")


# Siglas del dominio que NO son códigos de modo de falla. Sirve para bajar el
# ruido de lo que se manda a revisar, y NADA MÁS: el veredicto ya no depende de
# ella.
#
# Cuando sí lo sostenía, 72 de 79 siglas del oficio producían una acusación
# falsa —`RPM`, `BAR`, `ASME`, `OREDA`, `SSO`, `JSON`, el TAG `TK-12`, la
# cabecera `| MODO |`, y hasta `NO` escrito en mayúsculas por énfasis—: 11 de
# cada 12 respuestas correctas salían en rojo. Era la misma apuesta que perdió
# cuatro veces seguidas, con el error movido de «qué conector eligió el modelo»
# a «qué siglas del oficio mencionó». El vocabulario técnico no está acotado, y
# una lista escrita a mano no puede alcanzarlo.
SIGLAS_QUE_NO_SON_CODIGOS = frozenset({
    "RCM", "ISO", "SAE", "AMEF", "FMEA", "TAG", "CMMS", "GMAO", "FFI", "EPS",
    "UAT", "PDF", "CSV", "XLSX", "API", "URL", "HITL", "OK", "NA", "ND",
    "ABCD", "CC", "EXED", "MTBF", "MTTR", "RPN", "NPR", "SOD", "BF", "OHF",
})


def _codigos_ajenos(texto: str, del_catalogo: dict[str, str], preguntado: str = "") -> list[str]:
    """Siglas que el texto usa como códigos y que el catálogo del cliente no tiene.

    Esta comprobación NO lee prosa: compara dos conjuntos. Las siglas del texto
    contra las que la herramienta devolvió en esta misma corrida. Un código que
    el cliente no tiene es un invento, se escriba como se escriba.

    Es lo que sustituye a cuatro rondas de cortar el texto para adivinar qué
    definición se atribuía a qué código. Aquello intentaba decidir una frontera
    de discurso con dos miradas de un carácter, y cada arreglo movía el fallo de
    flanco: la última versión ponía en rojo 129 de 380 respuestas correctas
    según qué conector eligiera el modelo —«También» fallaba, «y» pasaba—.
    """
    if not del_catalogo:
        # Sin catálogo no hay contra qué comparar, y dar por ajeno todo lo que
        # parezca una sigla acusaría de inventar justo al que citó bien los
        # veinte códigos del cliente. Se abstiene: el que no haya catálogo lo
        # reporta `_definiciones_de_la_herramienta`, no esta función.
        return []
    # Tres o cuatro letras: es la forma de los códigos del cliente. Con dos,
    # entraban `PT` de un TAG, `PM` de un plan, `QA`, `NO` en mayúsculas… y
    # ninguna es un modo de falla. El dígito sí se admite porque el propio
    # código que se pregunta —QQQ1— lo lleva.
    candidatas = set(re.findall(r"\b[A-Z]{3,4}\d?\b", texto))
    ajenas = candidatas - set(del_catalogo) - SIGLAS_QUE_NO_SON_CODIGOS
    return sorted(ajenas - {preguntado.upper()})


def _significados_para_revisar(texto: str, reales: dict[str, str]) -> list[str]:
    """Lo que el texto parece atribuir a cada código, para que lo mire una persona.

    Sale de la misma maquinaria de antes, pero ya no decide: imprime. La
    diferencia importa, porque como veredicto se equivocaba en las dos
    direcciones —absolvía inversiones reales y acusaba citas literales del
    catálogo— y ninguna de las dos se veía sin un barrido de 380 pares.
    """
    definidos, sospechas = _codigos_definidos(texto, reales)
    if not definidos:
        return []
    return [f"atribuye significado a {', '.join(definidos)}",
            *(f"posible inversión: {s}" for s in sospechas)]


def _juzgar_codigo_iso(
    texto: str, preguntado: str, reales: dict[str, str]
) -> tuple[bool, str, list[str]]:
    """Criterio 29: la parte que se puede decidir sin interpretar lenguaje.

    Dos comprobaciones, las dos de conjuntos y ninguna de gramática:

    - Que diga que el código preguntado no está en el catálogo.
    - Que no use ninguna sigla como código fuera del catálogo del cliente.

    La tercera —«no inventa el SIGNIFICADO de los códigos que sí existen»— no
    se decide aquí. Se devuelve como evidencia para revisión humana. Cuatro
    rondas seguidas produjeron cuatro veredictos distintos sobre los mismos
    textos sin que el producto cambiara: un instrumento así no mide, opina, y
    un ✅ suyo vale menos que un «no lo sé» honesto.
    """
    # Sin la decoración: «**NO** existe» partía la frase en dos y la negación
    # dejaba de reconocerse, así que enfatizar la respuesta la suspendía.
    plano = re.sub(r"[*_`]+", "", texto).lower()
    # La MISMA lista que usa `_significado_atribuido`. Estaban duplicadas y se
    # desincronizaron: la ronda 26 añadió trece formas a una sola, así que
    # «QQQ1 — no se encuentra en la base de códigos» dejaba de leerse como
    # invento y seguía suspendiendo por no declararlo ausente. Diez formas
    # correctas en rojo por tener la misma verdad escrita en dos sitios.
    # Unificar las listas arregló la desincronización y abrió un verde falso:
    # buscar las ~30 formas como subcadena en TODO el texto aprobaba inventos
    # que nunca declaran ausente el código. «nada en» casaba dentro de
    # «determiNADA EN», y «pendiente de» o «no se pudo» son frases corrientes en
    # un análisis por motivos que no tienen que ver con el catálogo.
    #
    # Se busca con frontera de palabra, y las genéricas no cuentan: afirman una
    # abstención, no una ausencia.
    dice_que_no_existe = any(
        re.search(rf"\b{re.escape(p.replace('ó', 'o'))}", plano.replace("ó", "o"))
        for p in _NEGACIONES
        if p not in _ABSTENCIONES
    ) or bool(re.search(r"\bno encontr[eé]", plano))
    # Esto SÍ se decide: si el catálogo del cliente no tiene el código,
    # cualquier significado que se le dé es inventado, sin comparar nada con
    # nada. Y falla por defecto —se le escapa un invento antes que acusar a una
    # negación—, que es la dirección correcta para un instrumento de medida.
    invento = _significado_atribuido(texto, preguntado, tuple(reales))
    evidencia = (
        f"lo declara ausente: {dice_que_no_existe} | "
        f"catálogo leído: {len(reales)} códigos"
    )
    if invento:
        evidencia += f" | le atribuye un significado: «{invento}»"
    if not reales:
        # Se cuenta como fallo, no como «nada que comprobar». El criterio dice
        # «usa explain_iso_code»: si de su salida no sale ni un código, o no la
        # llamó o el instrumento dejó de saber leerla, y las dos cosas hay que
        # verlas. Antes esto salía en VERDE con la evidencia diciendo
        # «códigos fuera del catálogo: ninguno», que se lee como una medición
        # hecha y era una abstención muda.
        evidencia += " | ⚠ CATÁLOGO VACÍO: no se pudo comprobar nada contra él"
    ajenos = _codigos_ajenos(texto, reales, preguntado)
    revisar = _significados_para_revisar(texto, reales)
    if ajenos:
        revisar.append(f"siglas que el catálogo no tiene: {', '.join(ajenos)}")
    return (
        dice_que_no_existe and not invento and bool(reales),
        evidencia,
        revisar,
    )


def _veces_que_llamo(salidas: list[dict], herramienta: str) -> int:
    """En cuántos de los turnos se llamó a la herramienta.

    Extraído del bucle de `main()`: allí no había forma de probarlo, y el
    criterio 8 podía reportar siempre 0/3 sin que nada lo notara.
    """
    return sum(1 for s in salidas if herramienta in _herramientas(s))


def _medicion_compuerta(llamadas: int, intentos: int) -> str:
    """La línea de medición del criterio 8. Mide, no aprueba: depende de ALTA-2."""
    return (
        f"[8] La compuerta la decide la herramienta: {llamadas}/{intentos} "
        "(ALTA-2, limitación conocida; el botón es el camino garantizado)"
    )


def _evaluar_criterio_29(salida: dict, preguntado: str) -> tuple[bool, str, list[str]]:
    """Criterio 29 entero, contra la salida real de la herramienta.

    El catálogo lo pone `explain_iso_code` en esta misma corrida, no una tabla
    de palabras clave elegida a mano: los tres intentos anteriores fallaron por
    medir contra mi criterio en vez de contra el del sistema.
    """
    reales = _definiciones_de_la_herramienta(salida)
    return _juzgar_codigo_iso(salida.get("content") or "", preguntado, reales)


def _codigo_final(
    veredicto: int, hallazgos: list[dict], interrumpida: bool, fugadas: list[str]
) -> int:
    """El código de salida, con todo lo que pudo pasar en la corrida.

    0 bien · 1 criterio en rojo · 2 corrida truncada · 4 la corrida ensució la
    base del cliente. (3 lo devuelve `main` antes de empezar: error de operador;
    5 lo devuelve el arranque si el arnés revienta.)

    Extraída porque vivía dentro de `main()` y no había forma de probarla: se
    podía hacer que una truncación escondiera los rojos ya medidos, o que una
    sesión fugada saliera en verde, sin que nada chillara.
    """
    if fugadas:
        return 4
    if interrumpida:
        # Los criterios que faltan, faltan POR la truncación y no cuentan; los
        # rojos ya medidos sí, y mandan sobre el 2.
        return 1 if any(not h["ok"] for h in hallazgos) else 2
    return veredicto


def _veredicto(
    hallazgos: list[dict],
    mediciones: list[str],
    no_ejecutados: list[str],
    revisiones: list[str] | None = None,
) -> int:
    """Imprime el resumen y devuelve el código de salida.

    Extraída de `main()` para poder probarla: el validador demostró que se podían
    revertir los dos arreglos del veredicto —el denominador fijo y «un
    obligatorio sin evaluar cuenta como fallo»— con la suite entera en verde,
    porque nada de `main()` estaba cubierto.

    Denominador FIJO: con `len(hallazgos)` como total, un criterio que dejaba de
    ser evaluable bajaba el total y se imprimía «8/8 en verde» con salida 0, o
    sea una regresión que se manifiesta como menos criterios comprobados.
    """
    fallidos = [h for h in hallazgos if not h["ok"]]
    evaluados = {h["criterio"] for h in hallazgos}
    obligatorios = [h for h in hallazgos if h["criterio"] in ESPERADOS]
    verdes = len([h for h in obligatorios if h["ok"]])
    print(f"\n{verdes}/{len(ESPERADOS)} criterios obligatorios en verde.")
    faltan = [n for n in ESPERADOS if n not in evaluados]
    if faltan:
        # Con nombre, no con números pelados: es lo que se hace en el resto.
        print("  ⚠ obligatorios SIN EVALUAR (cuenta como fallo):")
        for n in faltan:
            print(f"      [{n}]")
    medidos = {int(m.split("]")[0].lstrip("[")) for m in mediciones if m.startswith("[")}
    for n, desc in CONDICIONALES.items():
        if n not in evaluados and n not in medidos:
            print(f"  📏 [{n}] no evaluable en esta corrida — {desc}")
    for medicion in mediciones:
        print(f"  📏 {medicion}")
    for pendiente in no_ejecutados:
        print(f"  ⊘ NO EJECUTADO {pendiente}")
    for numero, desc in REQUIEREN_OJO.items():
        print(f"  👁 [{numero}] REQUIERE OJO HUMANO — {desc}")
    # Cada línea bajo SU criterio: iban todas indentadas tras el encabezado del
    # 40, así que lo que había que revisar del 29 —una posible inversión de
    # significado— se leía como evidencia del 40.
    pendientes = revisiones or []
    if pendientes:
        print(f"\n  👁 {len(pendientes)} puntos para revisar a mano "
              "(la corrida NO los juzga; su veredicto no los cuenta):")
        for linea in pendientes:
            print(f"      {linea}")
    if fallidos:
        print("Fallidos:")
        for h in fallidos:
            print(f"  ❌ [{h['criterio']}] {h['descripcion']} — {h['evidencia'][:90]}")
    # Un obligatorio sin evaluar cuenta como fallo.
    return 1 if (fallidos or faltan) else 0


def main() -> int:
    if not LLAVE:
        print("✗ Falta OS_SECURITY_KEY en el entorno.")
        return 3  # error del operador, ni fallo del producto ni corrida truncada

    with httpx.Client() as cliente:
        atiende, detalle = _proveedor_atiende(cliente)
        if not atiende:
            print(f"✗ El proveedor del modelo no atiende: {detalle}")
            print("  Los once criterios de esta lista necesitan un turno real del")
            print("  agente. Recargue la cuenta y vuelva a ejecutar.")
            # 2, igual que si cae a mitad: es la MISMA avería medida en otro
            # momento, y devolver 1 aquí significaba «el producto falló».
            return 2
        print(f"✓ El proveedor atiende ({detalle}). Ejecutando los criterios.\n")

        interrumpida = False
        fugadas: list[str] = []
        sufijo = uuid.uuid4().hex[:8]
        sesiones: list[str] = []
        hallazgos: list[dict] = []
        no_ejecutados: list[str] = []
        mediciones: list[str] = []
        revisiones: list[str] = []

        def sesion(nombre: str) -> str:
            sid = f"uat-{nombre}-{sufijo}"
            sesiones.append(sid)
            return sid

        try:
            # 1 — español, una pregunta a la vez.
            s = sesion("idioma")
            salida = _turno(cliente, s, "Buenas, quiero analizar la bomba P-101.")
            texto = salida.get("content") or ""
            # Una respuesta vacía pasaba, y una íntegramente en inglés que no
            # usara las cuatro cadenas de la lista negra también.
            palabras_es = ("el ", "la ", "que ", "para ", "con ", "de ")
            hay_respuesta = len(texto.strip()) > 40
            parece_espanol = sum(p in texto.lower() for p in palabras_es) >= 3
            sin_ingles = not any(
                p in texto for p in ("Error code", "Please", "the following", "Sorry")
            )
            hallazgos.append(_resultado(
                1, "Responde en español y con contenido",
                hay_respuesta and parece_espanol and sin_ingles, texto[:120]))

            # 4 — pregunta por funciones de protección (ahí viven las ocultas).
            s = sesion("oculta")
            _turno(cliente, s, "Analicemos la bomba P-101 de la planta norte, TAG P-101.")
            salida = _turno(
                cliente, s,
                "Su función primaria es bombear crudo a 250 m³/h a 12 bar. "
                "¿Qué más necesitas saber de sus funciones?",
            )
            def _pregunta_por_proteccion(t: str) -> bool:
                return any(
                    p in t.lower() for p in ("protección", "proteccion", "alarma",
                                             "disparo", "válvula de seguridad", "respaldo")
                )

            # Hasta tres turnos: el facilitador reparte las preguntas, y medirlo
            # en uno solo mide la suerte, no el método. Lo que importa es que no
            # cierre la fase 2 sin preguntar por las protecciones.
            texto = salida.get("content") or ""
            pregunta = _pregunta_por_proteccion(texto)
            for _ in range(2):
                if pregunta:
                    break
                salida = _turno(cliente, s, "De acuerdo. ¿Qué más necesitas?")
                texto = salida.get("content") or ""
                pregunta = _pregunta_por_proteccion(texto)
            hallazgos.append(_resultado(
                4, "Pregunta por las funciones de protección", pregunta, texto[:140]))

            # 8 y 27 — la compuerta del entregable la decide la herramienta.
            #
            # Estos dos MIDEN, no aprueban. Dependen de ALTA-2 —el agente decide
            # la compuerta por su cuenta en vez de llamar a export_excel—, que
            # está documentada y aceptada, con el botón como camino garantizado.
            # Fallar por ella dejaba el código de salida oscilando entre 0 y 1
            # según lo que decidiera el modelo esa vez, y una puerta que
            # parpadea no sirve de puerta: un fallo real no se distinguiría.
            salidas = []
            for intento in range(3):
                s = sesion(f"compuerta{intento}")
                _turno(cliente, s, "Analicemos la bomba P-102, TAG P-102, planta sur.")
                salidas.append(_turno(
                    cliente, s, "Quiero el Excel definitivo, el entregable final."))
            salida = salidas[-1]
            usadas = _herramientas(salida)
            llamadas = _veces_que_llamo(salidas, "export_excel")
            mediciones.append(_medicion_compuerta(llamadas, 3))
            print(f"  📏 [8] export_excel llamado en {llamadas}/3 intentos (ALTA-2)")
            # Distinto del criterio 8: aquí se comprueba que los faltantes que
            # enumera vengan de la herramienta. Se contrastan contra los que
            # devuelve el endpoint del botón, que no pasa por el modelo.
            # Los faltantes reales vienen en el `result` de la propia llamada a
            # export_excel: es lo que devolvió la herramienta, no lo que el
            # modelo dice que devolvió. El endpoint del botón no sirve para
            # esto —entrega un BORRADOR válido, no una lista de bloqueadores.
            # Exigir coincidencia literal era demasiado frágil: el agente
            # parafrasea, y eso es correcto. Lo que NO puede hacer es enumerar
            # fases pendientes que la herramienta no mencionó — esa es la firma
            # de la lista inventada. Observado en producción: «Si intento
            # exportar ahora, la herramienta va a rechazarlo» seguido de las
            # seis fases, sin haberla llamado.
            # 27 — solo se puede juzgar en los intentos donde SÍ llamó: si no
            # llamó, lo que se está midiendo es ALTA-2, no la fidelidad de los
            # faltantes. La firma de la lista inventada es enumerar fases que la
            # herramienta no mencionó.
            reales = _faltantes_de_la_herramienta(salida)
            texto_rechazo = salida.get("content") or ""
            inventadas = sorted(
                _fases_mencionadas(texto_rechazo) - _fases_mencionadas(" ".join(reales))
            )
            if "export_excel" not in usadas:
                mediciones.append(
                    "[27] No evaluable en este intento: el agente no llamó a "
                    "export_excel (ALTA-2)"
                )
                print("  📏 [27] no evaluable en este intento (ALTA-2)")
            else:
                hallazgos.append(_resultado(
                    27, "Los faltantes que enumera salen de la herramienta",
                    bool(reales) and not inventadas,
                    f"fases inventadas: {inventadas}" if inventadas
                    else f"faltantes de la herramienta: {reales[:2]}"))

            # 23 y 25 — exportación por chat y enlace clicable.
            #
            # Se comprueba que el alcance quedó REGISTRADO antes de pedir el
            # borrador: si la sesión está vacía el agente se niega a generarlo,
            # y entonces lo que se mide es si registró el TAG, no si la
            # exportación por chat funciona. Observado: un primer turno con el
            # TAG dentro no siempre lo registra.
            s = sesion("export")
            _turno(cliente, s, "Analicemos la bomba P-103, TAG P-103.")
            if not _hay_alcance(cliente, s):
                _turno(cliente, s,
                       "Registra ahora el alcance: activo «Bomba centrífuga P-103», "
                       "TAG «P-103», ubicación «planta norte».")
            salida = _turno(cliente, s, "Dame un borrador del Excel con lo que llevamos.")
            texto = salida.get("content") or ""
            # No basta con que la herramienta se llame: también se llama cuando
            # RECHAZA. Tiene que salir un enlace de descarga.
            hallazgos.append(_resultado(
                23, "La exportación por chat entrega algo descargable",
                "export_excel" in _herramientas(salida) and "](/exports/" in texto,
                texto[:140]))
            hallazgos.append(_resultado(
                25, "Entrega el enlace /exports/… clicable, sin ?key=",
                "](/exports/" in texto and "?key=" not in texto, texto[:160]))

            # 29 — código ISO fuera del catálogo, sin inventar significados.
            s = sesion("iso")
            salida = _turno(
                cliente, s,
                "¿Qué significa el código ISO 14224 'QQQ1'? Usa explain_iso_code.")
            ok29, evidencia29, revisar29 = _evaluar_criterio_29(salida, "QQQ1")
            hallazgos.append(_resultado(
                29, "Declara ausente el código y no usa siglas fuera del catálogo",
                ok29, evidencia29))
            revisiones += [f"[29] {r}" for r in revisar29]

            # 40 — siglas preguntadas a pelo, sin ejecutar herramientas. No se
            # puntúa: se transcribe para que lo lea una persona.
            s = sesion("siglas")
            salida = _turno(
                cliente, s,
                "En mi Excel veo la columna «Falla Evidente (ABCD)». ¿Qué significa "
                "cada letra, y qué significan CC y ExEd?")
            revisiones.append(f"[40] respuesta literal: {(salida.get('content') or '')[:400]}")

            # 36 — lo que el agente dice haber registrado está en la sesión.
            s = sesion("estado")
            _turno(cliente, s, "Analicemos la bomba P-104, TAG P-104, planta este.")
            _turno(cliente, s,
                   "El equipo somos Ana Pérez de mantenimiento y Luis Gómez de "
                   "operaciones. Regístralos a los dos.")
            estado = cliente.get(
                f"{BASE}/sessions/{s}", headers=_cabeceras(), timeout=120).json()
            # Contra el estado del análisis, NO contra el JSON entero: ese
            # incluye el historial de mensajes, o sea el texto que este mismo
            # script acaba de enviar. Peor: «Analicemos», con la que se abre la
            # sesión, contiene «Ana». Probado — la aserción vieja daba True con
            # el equipo vacío.
            equipo = _equipo_registrado(estado)
            nombres = " ".join(equipo).lower()
            hallazgos.append(_resultado(
                36, "Nada se pierde en un turno con varias herramientas",
                "ana" in nombres and "luis" in nombres,
                f"equipo en session_state: {equipo or 'VACÍO'}"))

            # 10 — la sesión se reanuda con su estado.
            salida = _turno(cliente, s, "¿Cómo vamos? ¿Qué falta?")
            texto = salida.get("content") or ""
            hallazgos.append(_resultado(
                10, "Reanuda la sesión sabiendo lo ya registrado",
                "P-104" in texto or "Ana" in texto, texto[:140]))

            # 26 — ante un fallo técnico cita el error y no inventa la causa.
            # NO EJECUTADO, y no cuenta como fallo: codificarlo a False dejaba
            # el script permanentemente en rojo, así que un fallo real de los
            # otros diez no se distinguía del estado normal.
            no_ejecutados.append(
                "[26] Ante un fallo técnico cita el error — provocarlo exige romper "
                "algo del entorno del cliente")

        except ProveedorCaido as exc:
            print(f"\n✗ El proveedor dejó de atender a mitad de corrida: {exc}")
            print("  Los criterios que quedaban NO se han medido.")
            interrumpida = True
        finally:
            for sid in sesiones:
                _borrar(cliente, sid)
            try:
                restantes = cliente.get(
                    f"{BASE}/sessions?limit=100", headers=_cabeceras(), timeout=120
                ).json()
            except Exception as exc:  # noqa: BLE001 — el recuento informa, no manda
                # Sin esta guarda, un 502 del borde (que llega como HTML) lanzaba
                # ValueError DENTRO del finally y se comía el `return 2`: el
                # arreglo del código de salida lo anulaba la respuesta de un WAF.
                print(f"\nLimpieza: hecha, pero no se pudo verificar el censo ({exc})")
            else:
                crudo = json.dumps(restantes)
                fugadas[:] = [sid for sid in sesiones if sid in crudo]
                print(
                    f"\nLimpieza: {'quedan ' + str(fugadas) if fugadas else 'sin residuos'}"
                )

        # El veredicto se imprime SIEMPRE, también al truncarse: saltárselo
        # escondía los criterios ya medidos en rojo y el script llegaba a
        # afirmar que no había fallo del producto cuando ya había medido uno.
        codigo = _veredicto(hallazgos, mediciones, no_ejecutados, revisiones)
        if fugadas:
            print("  ⚠ La corrida dejó sesiones en la base del cliente.")
        return _codigo_final(codigo, hallazgos, interrumpida, fugadas)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — el código de salida tiene que decir la verdad
        # 5, no 1: un fallo del arnés (red, JSON, KeyError) no es un criterio en
        # rojo, y salir con 1 lo hacía indistinguible de un defecto del producto.
        print(f"\n✗ El arnés falló, no el producto: {type(exc).__name__}: {exc}")
        sys.exit(5)
