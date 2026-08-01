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
import sys
import uuid

import httpx

BASE = os.environ.get("RCM_BASE_URL", "https://rcm-demo.beautomata.com")
LLAVE = os.environ.get("OS_SECURITY_KEY") or os.environ.get("RCM_OS_SECURITY_KEY") or ""
TIEMPO = 240.0


def _cabeceras() -> dict[str, str]:
    return {"Authorization": f"Bearer {LLAVE}"}


def _turno(cliente: httpx.Client, sesion: str, mensaje: str) -> dict:
    r = cliente.post(
        f"{BASE}/agents/facilitador-rcm/runs",
        headers=_cabeceras(),
        data={"message": mensaje, "stream": "false", "session_id": sesion},
        timeout=TIEMPO,
    )
    r.raise_for_status()
    return r.json()


def _herramientas(salida: dict) -> list[str]:
    return [t.get("tool_name") for t in (salida.get("tools") or [])]


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


def _faltantes_del_boton(cliente: httpx.Client, sesion: str) -> list[str]:
    """Los bloqueadores reales, pedidos por el camino que no pasa por el modelo."""
    r = cliente.get(f"{BASE}/exports/{sesion}", headers=_cabeceras(), timeout=120)
    if r.status_code == 200:
        return []
    try:
        detalle = r.json().get("detail", "")
    except ValueError:
        return []
    return [linea.strip("- ").strip() for linea in str(detalle).splitlines() if "-" in linea]


def _nucleo(faltante: str) -> str:
    """La parte del faltante que se puede buscar en la respuesta del agente."""
    limpio = faltante.split("]")[-1].strip().lower()
    return limpio[:28]


def _proveedor_atiende(cliente: httpx.Client) -> tuple[bool, str]:
    r = cliente.get(f"{BASE}/health/modelo", headers=_cabeceras(), timeout=120)
    try:
        cuerpo = r.json()
    except ValueError:
        # Un 502 de Cloudflare llega como HTML: reventar aquí con un
        # JSONDecodeError contradice justo lo que esta función promete.
        return False, f"respuesta no-JSON del borde (HTTP {r.status_code})"
    return r.status_code == 200, cuerpo.get("detalle", "")


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

        sufijo = uuid.uuid4().hex[:8]
        sesiones: list[str] = []
        hallazgos: list[dict] = []
        no_ejecutados: list[str] = []

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
            texto = (salida.get("content") or "").lower()
            pregunta = any(
                p in texto for p in ("protección", "proteccion", "alarma", "disparo",
                                     "válvula de seguridad", "respaldo")
            )
            hallazgos.append(_resultado(
                4, "Pregunta por las funciones de protección", pregunta, texto[:140]))

            # 8 y 27 — la compuerta del entregable la decide la herramienta.
            s = sesion("compuerta")
            _turno(cliente, s, "Analicemos la bomba P-102, TAG P-102, planta sur.")
            salida = _turno(cliente, s, "Quiero el Excel definitivo, el entregable final.")
            usadas = _herramientas(salida)
            hallazgos.append(_resultado(
                8, "El rechazo del export sale de export_excel",
                "export_excel" in usadas, f"herramientas: {usadas}"))
            # Distinto del criterio 8: aquí se comprueba que los faltantes que
            # enumera vengan de la herramienta. Se contrastan contra los que
            # devuelve el endpoint del botón, que no pasa por el modelo.
            reales = _faltantes_del_boton(cliente, s)
            texto_rechazo = salida.get("content") or ""
            coincide = bool(reales) and any(
                _nucleo(f) and _nucleo(f) in texto_rechazo.lower() for f in reales
            )
            hallazgos.append(_resultado(
                27, "Los faltantes son los reales, no una lista inventada",
                "export_excel" in usadas and coincide,
                f"faltantes reales: {reales[:2]}"))

            # 23 y 25 — exportación por chat y enlace clicable.
            s = sesion("export")
            _turno(cliente, s, "Analicemos la bomba P-103, TAG P-103.")
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
            inventados = [
                k for k, v in reales.items()
                if k in texto and v not in texto[texto.index(k):texto.index(k) + 90].lower()
            ]
            mencionados = [k for k in reales if k in texto]
            hallazgos.append(_resultado(
                29, "No inventa el significado de los códigos ISO",
                bool(mencionados) and not inventados,
                f"mencionados: {mencionados or 'NINGUNO (aserción vacua)'} | "
                f"inventados: {inventados or 'ninguno'}"))

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

        finally:
            for sid in sesiones:
                try:
                    cliente.delete(f"{BASE}/sessions/{sid}", headers=_cabeceras(),
                                   timeout=60)
                except Exception as exc:  # noqa: BLE001 — la limpieza informa, no revienta
                    print(f"  ⚠ no se pudo borrar {sid}: {exc}")
            restantes = cliente.get(
                f"{BASE}/sessions?limit=100", headers=_cabeceras(), timeout=120).json()
            crudo = json.dumps(restantes)
            fugadas = [sid for sid in sesiones if sid in crudo]
            print(f"\nLimpieza: {'quedan ' + str(fugadas) if fugadas else 'sin residuos'}")

        fallidos = [h for h in hallazgos if not h["ok"]]
        print(f"\n{len(hallazgos) - len(fallidos)}/{len(hallazgos)} criterios en verde.")
        for pendiente in no_ejecutados:
            print(f"  ⊘ NO EJECUTADO {pendiente}")
        if fallidos:
            print("Fallidos:")
            for h in fallidos:
                print(f"  ❌ [{h['criterio']}] {h['descripcion']} — {h['evidencia'][:90]}")
        # Sale 0 si no hay fallos. Antes el criterio 26 estaba codificado a
        # False, así que el script nunca podía salir 0 y como puerta de CI
        # estaba permanentemente en rojo: un fallo real no se distinguía del
        # estado normal.
        return 1 if fallidos else 0


if __name__ == "__main__":
    sys.exit(main())
