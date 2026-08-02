#!/usr/bin/env python
"""Prueba de mutación honesta: rompe el código a propósito y exige que falle.

Existe porque llevaba muchas rondas rehaciendo este arnés a mano en la consola,
y así se cuelan tres errores que hacen mentir la medición:

1. **La caché de bytecode.** Una mutación de la MISMA longitud —`{4,120}` por
   `{1,120}`— deja el fichero con idéntico tamaño, y si la marca de tiempo cae
   en el mismo tic, Python reutiliza el `.pyc` viejo. La suite entonces prueba
   el código sin mutar y el mutante se declara MUERTO o VIVO por azar. Pasó de
   verdad, y precisamente con las mutaciones de un carácter, que son las más
   afiladas.
2. **El reemplazo que no aplica.** Un `str.replace` que no encuentra su texto no
   avisa: devuelve el original y el mutante se apunta como superviviente sin
   haber existido.
3. **El reemplazo que aplica de más.** Con dos coincidencias, se muta más de lo
   que se cree y el resultado no dice nada del sitio que se quería probar.

Aquí las tres se comprueban: exactamente una coincidencia, el resultado tiene
que compilar, y cada corrida borra el `__pycache__` y desactiva su escritura.

    uv run python scripts/mutar.py mutaciones.json

El fichero es una lista de `{"nombre", "fichero", "antes", "despues", "suite"}`.
Devuelve 0 si mueren todas, 1 si sobrevive alguna, 2 si alguna es inválida: un
mutante vivo es un hueco de test, y uno inválido es una medición que no ocurrió.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _limpiar_cache() -> None:
    for directorio in RAIZ.rglob("__pycache__"):
        if ".venv" not in str(directorio):
            shutil.rmtree(directorio, ignore_errors=True)


def _correr(suite: str, tope: int = 600) -> int:
    """El código de salida de pytest. Sin caché de pytest ni de bytecode.

    Por `returncode`, no buscando «failed» en la salida. Buscar subcadenas se
    equivoca en las dos direcciones: una suite que no existe devuelve 4 con el
    texto «no tests ran», sin «failed» ni «error» en minúscula, así que el
    mutante se apuntaba como SUPERVIVIENTE —o sea, se fabricaba un hueco de test
    que no existe—; y cualquier test futuro cuyo nombre lleve esas letras
    declararía MUERTO a todo.

    0 = pasa · 1 = falla (el mutante muere) · lo demás = la corrida no ocurrió.
    """
    entorno = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        return subprocess.run(
            ["uv", "run", "pytest", "-q", "-p", "no:cacheprovider", suite],
            capture_output=True, text=True, cwd=RAIZ, env=entorno,
            # Con tope: un mutante puede colgar la suite —un bucle que no
            # termina—, y sin esto el arnés se queda esperando para siempre con
            # el fichero mutado en el árbol.
            timeout=tope,
        ).returncode
    except subprocess.TimeoutExpired:
        # -1 nunca es 0 ni 1, así que sube como INVÁLIDA. Devolver 0 haría que
        # un tope agotado EN LA LÍNEA BASE se leyera como verde, y el arnés
        # firmaría una medición sobre una suite que jamás terminó de correr:
        # justo la avería que este fichero existe para impedir.
        return -1


def mutar(mutaciones: list[dict]) -> int:
    # La línea base tiene que estar VERDE antes de tocar nada. Sin esto, con la
    # suite ya roja por cualquier motivo ajeno, todo mutante «muere» y el arnés
    # firma 0 con confianza total y cero medición. Se comprobó metiendo un
    # control que solo cambiaba una letra DENTRO DE UN COMENTARIO: salió
    # MUERTO. Un comentario no puede matar a nadie.
    for suite in sorted({m.get("suite", "tests") for m in mutaciones}):
        codigo = _correr(suite)
        if codigo != 0:
            print(f"  LÍNEA BASE ROJA en «{suite}» (pytest devolvió {codigo}).")
            print("  Nada de lo que midiera aquí significaría algo.")
            return 2
    invalidas, vivos = [], []
    for m in mutaciones:
        ruta = RAIZ / m["fichero"]
        original = ruta.read_text()
        if original.count(m["antes"]) != 1:
            invalidas.append(f"{m['nombre']}: {original.count(m['antes'])} coincidencias")
            continue
        mutado = original.replace(m["antes"], m["despues"], 1)
        if mutado == original:
            invalidas.append(f"{m['nombre']}: el reemplazo no cambia nada")
            continue
        try:
            ast.parse(mutado)
        except SyntaxError as exc:
            invalidas.append(f"{m['nombre']}: no compila ({exc.msg})")
            continue
        try:
            _limpiar_cache()
            ruta.write_text(mutado)
            codigo = _correr(m.get("suite", "tests"), m.get("tope", 600))
        finally:
            _limpiar_cache()
            ruta.write_text(original)
        if codigo not in (0, 1):
            invalidas.append(f"{m['nombre']}: pytest devolvió {codigo}, no llegó a correr")
            continue
        print(f"  {'VIVO  ' if codigo == 0 else 'MUERTO'}  {m['nombre']}")
        if codigo == 0:
            vivos.append(m["nombre"])

    for aviso in invalidas:
        print(f"  INVÁLIDA  {aviso}")
    if invalidas:
        print(f"\n{len(invalidas)} mutaciones no llegaron a medirse.")
        return 2
    if vivos:
        print(f"\n{len(vivos)} sobreviven — son huecos de test, no éxitos:")
        for nombre in vivos:
            print(f"  · {nombre}")
        return 1
    print(f"\nMueren las {len(mutaciones)}.")
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    return mutar(json.loads(Path(sys.argv[1]).read_text()))


if __name__ == "__main__":
    raise SystemExit(main())
