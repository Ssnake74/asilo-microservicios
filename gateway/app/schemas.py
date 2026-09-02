"""Modelos de entrada del Gateway."""

from pydantic import BaseModel, Field


class Credenciales(BaseModel):
    usuario: str = Field(min_length=3, max_length=40)
    contrasena: str = Field(min_length=6, max_length=100)
