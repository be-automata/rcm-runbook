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
ESPERADOS = (1, 4, 10, 23, 25, 29, 36, 40)
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


def _codigos_definidos(texto: str, reales: dict[str, str]) -> tuple[list[str], list[str]]:
    """Códigos a los que el agente les ATRIBUYE un significado, y cuáles falla.

    Listar un código sin definirlo no es inventárselo, y el criterio dice «no
    inventa el significado». La versión anterior miraba 90 caracteres desde la
    primera aparición y marcaba como inventado un código correctamente listado
    más abajo: dio un falso positivo con una respuesta que era correcta.
    """
    definidos: list[str] = []
    inventados: list[str] = []
    for codigo, esperado in reales.items():
        # Los formatos que el agente usa DE VERDAD. La versión anterior excluía
        # `|` de la clase, y resulta que responde con una tabla markdown: contra
        # la respuesta real no consideraba definido ni un solo código, así que la
        # mitad de «no inventa» quedaba vacua. Cambiar una medición porque falla
        # es la forma de aflojar la vara sin darse cuenta, y eso fue esto.
        m = re.search(
            rf"{codigo}\**\s*(?:[—:|-]|\bes\b|\bsignifica\b|\()\s*\**([^\n|)]{{4,70}})",
            texto,
        )
        if not m:
            continue
        definidos.append(codigo)
        if esperado not in m.group(1).lower():
            inventados.append(f"{codigo}→«{m.group(1).strip()[:40]}»")
    return definidos, inventados


def _significado_atribuido(texto: str, codigo: str) -> str:
    """¿Se le atribuye algún significado a un código que NO está en el catálogo?

    Es el caso central del criterio 29 y no lo cubría nada: «QQQ1 no existe,
    pero por su forma sería 'Falla de calidad tipo 1'» daba «lo declara ausente:
    True, inventados: ninguno» y aprobaba.
    """
    for frase in re.split(r"[.\n]", texto):
        if codigo not in frase:
            continue
        m = re.search(
            r"(?:sería|significaría|correspondería|se refiere a|podría (?:ser|significar)"
            r"|significa|es probablemente)\s+\**['«\"]?([^'»\"\n]{4,60})",
            frase, re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
        # También «| QQQ1 | Falla de calidad |» y «QQQ1 — Falla de calidad».
        m = re.search(rf"{codigo}\**\s*[—:|-]\s*\**([^|\n]{{4,60}})", frase)
        if m:
            return m.group(1).strip()
    return ""


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


def _juzgar_codigo_iso(texto: str, preguntado: str, reales: dict[str, str]) -> tuple[bool, str]:
    """Criterio 29, entero y comprobable.

    Dos mitades: que diga que el código no está en el catálogo —siempre
    comprobable— y que no atribuya significados falsos, ni a los códigos reales
    ni al preguntado. Esa última parte no la cubría nada: «QQQ1 no existe, pero
    por su forma sería 'Falla de calidad tipo 1'» aprobaba.
    """
    dice_que_no_existe = any(
        p in texto.lower()
        for p in ("no existe", "no está en el catálogo", "no aparece", "no figura")
    )
    definidos, inventados = _codigos_definidos(texto, reales)
    invento = _significado_atribuido(texto, preguntado)
    if invento:
        inventados = [*inventados, f"{preguntado}→«{invento}»"]
    evidencia = (
        f"lo declara ausente: {dice_que_no_existe} | "
        f"definidos: {definidos or 'ninguno (nada que juzgar)'} | "
        f"inventados: {inventados or 'ninguno'}"
    )
    return dice_que_no_existe and not inventados, evidencia


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


def _veredicto(
    hallazgos: list[dict], mediciones: list[str], no_ejecutados: list[str]
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
    if fallidos:
        print("Fallidos:")
        for h in fallidos:
            print(f"  ❌ [{h['criterio']}] {h['descripcion']} — {h['evidencia'][:90]}")
    # Un obligatorio sin evaluar cuenta como fallo.
    return 1 if (fallidos or faltan) else 0


def main() -> int:
    if not LLAVE:
        print("✗ Falta OS_SECURITY_KEY en el entorno.")
        return 2

    with httpx.Client() as cliente:
        atiende, detalle = _proveedor_atiende(cliente)
        if not atiende:
            print(f"✗ El proveedor del modelo no atiende: {detalle}")
            print("  Los once criterios de esta lista necesitan un turno real del")
            print("  agente. Recargue la cuenta y vuelva a ejecutar.")
            return 1
        print(f"✓ El proveedor atiende ({detalle}). Ejecutando los criterios.\n")

        interrumpida = False
        sufijo = uuid.uuid4().hex[:8]
        sesiones: list[str] = []
        hallazgos: list[dict] = []
        no_ejecutados: list[str] = []
        mediciones: list[str] = []

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
            texto = salida.get("content") or ""
            reales = {"FTS": "arrancar", "STP": "detener", "HIO": "alta", "LOO": "baja"}
            definidos, inventados = _codigos_definidos(texto, reales)
            # Dos partes: que diga que el código no está en el catálogo —siempre
            # comprobable— y que no invente significados, que solo se puede
            # juzgar si define alguno. Exigir que defina convertía en fallo una
            # respuesta correcta que se limitaba a listar los códigos.
            ok29, evidencia29 = _juzgar_codigo_iso(texto, "QQQ1", reales)
            hallazgos.append(_resultado(
                29, "Dice que el código no está en el catálogo y no inventa significados",
                ok29, evidencia29))

            # 40 — siglas preguntadas a pelo, sin ejecutar herramientas.
            s = sesion("siglas")
            salida = _turno(
                cliente, s,
                "En mi Excel veo la columna «Falla Evidente (ABCD)». ¿Qué significa "
                "cada letra, y qué significan CC y ExEd?")
            texto = (salida.get("content") or "").lower()
            aciertos = sum(x in texto for x in (
                "seguridad", "operacional", "control de calidad", "exploración de edad"))
            hallazgos.append(_resultado(
                40, "Acierta las letras de ruta y las siglas de política",
                aciertos >= 3, f"{aciertos}/4 conceptos correctos"))

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
            print("  Los criterios que quedaban NO se han medido. Esto no es un")
            print("  fallo del producto: recargue la cuenta y vuelva a ejecutar.")
            interrumpida = True
        finally:
            for sid in sesiones:
                _borrar(cliente, sid)
            restantes = cliente.get(
                f"{BASE}/sessions?limit=100", headers=_cabeceras(), timeout=120).json()
            crudo = json.dumps(restantes)
            fugadas = [sid for sid in sesiones if sid in crudo]
            print(f"\nLimpieza: {'quedan ' + str(fugadas) if fugadas else 'sin residuos'}")

        if interrumpida:
            # Código 2, distinto del 1: una corrida truncada no es lo mismo que
            # un criterio en rojo, y confundirlos es lo que hizo que seis
            # criterios sanos aparecieran como fallidos.
            return 2
        return _veredicto(hallazgos, mediciones, no_ejecutados)


if __name__ == "__main__":
    sys.exit(main())
