"""Excepciones que cruzan capas.

`ReglaDeNegocio` vivía en `agent/tools.py`, pero el dominio también necesita
rechazar datos (una tarea casi duplicada, por ejemplo) sin que la frontera lo
disfrace de avería del sistema. Vive aquí para que `models/` no tenga que
importar de `agent/`.
"""

from __future__ import annotations


class ReglaDeNegocio(Exception):
    """El método rechaza el dato — no es una avería del sistema.

    La diferencia importa río abajo: el agente trata el banner técnico como
    «algo se rompió», deja de trabajar y se inventa una causa. Un rechazo del
    método es lo contrario: el sistema funcionando, y el agente tiene que
    repreguntar con la opción correcta a la vista.
    """
