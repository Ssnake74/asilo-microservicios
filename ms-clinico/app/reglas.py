"""
Reglas de negocio del microservicio Clinico.

Funciones puras: no tocan la base ni saben que existe HTTP.
"""

PENDIENTE = "PENDIENTE"
COMPLETADA = "COMPLETADA"   # orden de examen con su resultado
DESPACHADA = "DESPACHADA"   # receta entregada por la farmacia


def texto_limpio(texto: str | None) -> str | None:
    """Quita los espacios de las orillas; un texto que queda vacio es None."""
    if texto is None:
        return None
    limpio = texto.strip()
    return limpio or None


def cantidad_de_despacho_valida(despachada: int, recetada: int) -> bool:
    """La farmacia entrega entre una unidad y lo recetado, nunca mas."""
    return 1 <= despachada <= recetada


def referencia_examen(orden_id: int) -> str:
    """Asi aparece el cargo del examen en la cuenta del familiar."""
    return f"EXAMEN-{orden_id}"


def referencia_receta(receta_id: int) -> str:
    return f"RECETA-{receta_id}"
