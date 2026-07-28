"""Página de chat directo para demos con interesados (sin cuenta os.agno.com).

Un solo enlace con la llave incrustada (`/demo?key=...`) abre un chat mínimo
que conversa con el Facilitador RCM. Pensado para que un no-técnico solo pegue
la URL y escriba. La llave viaja en el enlace, no está incrustada en el HTML.

La sesión sobrevive recargas y cambios de dispositivo: el id se guarda en
`localStorage` y se refleja en la barra de direcciones como `&session=`, así
que copiar la URL del teléfono a la computadora retoma el mismo análisis, con
el historial repintado desde `/sessions/{id}/runs`.

El HTML vive en `static/demo.html`, no en un string de Python: incrustado, todo
el JS pasaba primero por el escapado de Python, y un `\\n` dentro de un
`confirm()` se convirtió en salto de línea real y rompió el script entero en el
navegador. Aparte, así vuelven el resaltado y el linter de JS/CSS. Se lee con
`importlib.resources`, igual que `models/catalogs.py` con el catálogo.
"""

from __future__ import annotations

from importlib import resources

DEMO_HTML = (
    resources.files("rcm_runbook.static").joinpath("demo.html").read_text("utf-8")
)
