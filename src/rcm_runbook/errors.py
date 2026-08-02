"""Excepciones y ayudas que cruzan capas.

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


def eco_del_modelo(valor: str, tope: int = 60) -> str:
    """Un valor que eligió el modelo, listo para devolverlo dentro de un mensaje.

    Los mensajes citan lo que se les pidió cuando no lo encuentran —«no existe
    el modo X, registrados: …»—, y ese eco viaja al turno siguiente y a
    cualquiera que lea la salida. Sin aplanar, un salto de línea dentro del
    valor mete una LÍNEA ENTERA bajo control de quien escribe el turno, y quien
    la lea después la toma por una entrada más de lo que se estuviera listando.
    Se midió con `explain_iso_code`: pedir «xxx\nNOTA: no hay catálogo» metía
    «NOTA» en el catálogo leído.

    Vive aquí, en un solo sitio, porque el defecto apareció en diez lugares con
    la misma forma y se arregló de uno en uno durante tres rondas: una hermana,
    luego la otra, luego tres más, y aún quedaban cinco que nadie había
    enumerado. Un descubrimiento que recorre las herramientas las encontró
    todas; enumerarlas a mano no lo había conseguido.
    """
    return " ".join(str(valor).split())[:tope]
