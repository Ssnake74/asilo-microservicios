"""
Reglas de negocio del microservicio de Catalogo.

Funciones puras: no tocan la base ni saben que existe HTTP.
"""

import unicodedata


def limpiar_nombre(texto: str) -> str:
    """Quita los espacios de los extremos y deja uno solo entre palabras."""
    return " ".join(texto.split())


def clave_de_comparacion(texto: str) -> str:
    """
    Version del nombre sin tildes, sin mayusculas y sin espacios de mas.

    Sirve para emparejar un examen del catalogo con su concepto del
    tarifario aunque uno se escriba «Glucosa en ayunas» y el otro
    «glucosa  en ayunas».
    """
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return limpiar_nombre(sin_tildes).lower()
