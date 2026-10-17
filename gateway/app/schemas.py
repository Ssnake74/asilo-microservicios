"""Modelos de entrada del Gateway."""

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .seguridad import ROLES

Rol = Literal[ROLES]

# Letras sin tildes, numeros, punto, guion y guion bajo: el nombre de
# usuario se escribe a mano en cualquier teclado.
FORMA_USUARIO = re.compile(r"^[a-z0-9._-]{3,40}$")


class Credenciales(BaseModel):
    usuario: str = Field(min_length=3, max_length=40)
    contrasena: str = Field(min_length=6, max_length=100)


def _nombre_limpio(valor: str) -> str:
    limpio = " ".join(valor.split())
    if len(limpio) < 3:
        raise ValueError("El nombre completo debe tener al menos 3 letras.")
    return limpio


class UsuarioCrear(BaseModel):
    usuario: str = Field(min_length=3, max_length=40)
    nombre: str = Field(min_length=3, max_length=120)
    rol: Rol

    @field_validator("usuario")
    @classmethod
    def forma_del_usuario(cls, valor: str) -> str:
        limpio = valor.strip().lower()
        if not FORMA_USUARIO.match(limpio):
            raise ValueError(
                "Use solo letras sin tildes, números, punto, guion o guion bajo, sin espacios."
            )
        return limpio

    @field_validator("nombre")
    @classmethod
    def nombre_limpio(cls, valor: str) -> str:
        return _nombre_limpio(valor)


class UsuarioActualizar(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=3, max_length=120)
    rol: Optional[Rol] = None
    activo: Optional[bool] = None

    @field_validator("nombre")
    @classmethod
    def nombre_limpio(cls, valor: Optional[str]) -> Optional[str]:
        return None if valor is None else _nombre_limpio(valor)


class CambioContrasena(BaseModel):
    actual: str = Field(min_length=1, max_length=100)
    nueva: str = Field(min_length=1, max_length=100)
