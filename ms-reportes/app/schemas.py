"""
Forma de salida de los informes.

Los siete informes tienen la misma forma, para que la pantalla los dibuje
todos con el mismo codigo y se impriman igual: un titulo, el resumen de
cifras arriba y una o varias tablas.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel

TipoDato = Literal["texto", "dinero", "fecha", "numero"]


class Columna(BaseModel):
    clave: str
    titulo: str
    tipo: TipoDato = "texto"


class Cifra(BaseModel):
    etiqueta: str
    valor: Any
    tipo: TipoDato = "dinero"


class Seccion(BaseModel):
    titulo: str
    columnas: list[Columna]
    filas: list[dict[str, Any]]
    # Fila final con las sumas, solo en las columnas que se suman.
    totales: Optional[dict[str, Any]] = None
    vacio: str = "No hay registros para estos filtros."


class Informe(BaseModel):
    clave: str
    titulo: str
    requisito: str
    filtros: str
    generado: str
    resumen: list[Cifra] = []
    secciones: list[Seccion] = []
