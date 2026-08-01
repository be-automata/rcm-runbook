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


def _proveedor_atiende(cliente: httpx.Client) -> tuple[bool, str]:
    r = cliente.get(f"{BASE}/health/modelo", headers=_cabeceras(), timeout=120)
    cuerpo = r.json()
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

        def sesion(nombre: str) -> str:
            sid = f"uat-{nombre}-{sufijo}"
            sesiones.append(sid)
            return sid

        try:
            # 1 — español, una pregunta a la vez.
            s = sesion("idioma")
            salida = _turno(cliente, s, "Buenas, quiero analizar la bomba P-101.")
            texto = salida.get("content") or ""
            sin_ingles = not any(
                p in texto for p in ("Error code", "Please", "the following", "Sorry")
            )
            hallazgos.append(_resultado(1, "Responde en español", sin_ingles, texto[:120]))

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
            hallazgos.append(_resultado(
                27, "Los faltantes son los reales, no una lista inventada",
                "export_excel" in usadas, f"herramientas: {usadas}"))

            # 23 y 25 — exportación por chat y enlace clicable.
            s = sesion("export")
            _turno(cliente, s, "Analicemos la bomba P-103, TAG P-103.")
            salida = _turno(cliente, s, "Dame un borrador del Excel con lo que llevamos.")
            texto = salida.get("content") or ""
            hallazgos.append(_resultado(
                23, "La exportación por chat funciona",
                "export_excel" in _herramientas(salida), texto[:120]))
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
            hallazgos.append(_resultado(
                29, "No inventa el significado de los códigos ISO",
                not inventados, f"inventados: {inventados or 'ninguno'}"))

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
            crudo = json.dumps(estado)
            hallazgos.append(_resultado(
                36, "Nada se pierde en un turno con varias herramientas",
                "Ana" in crudo and "Luis" in crudo, "ambos integrantes en /sessions"))

            # 10 — la sesión se reanuda con su estado.
            salida = _turno(cliente, s, "¿Cómo vamos? ¿Qué falta?")
            texto = salida.get("content") or ""
            hallazgos.append(_resultado(
                10, "Reanuda la sesión sabiendo lo ya registrado",
                "P-104" in texto or "Ana" in texto, texto[:140]))

            # 26 — ante un fallo técnico cita el error y no inventa la causa.
            hallazgos.append(_resultado(
                26, "Ante un fallo técnico cita el error (requiere provocar uno real)",
                False, "NO EJECUTADO: provocarlo exige romper algo del entorno"))

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
        if fallidos:
            print("Pendientes:")
            for h in fallidos:
                print(f"  ❌ [{h['criterio']}] {h['descripcion']} — {h['evidencia'][:90]}")
        return 1 if fallidos else 0


if __name__ == "__main__":
    sys.exit(main())
