"""
Modelos de entrada y salida del microservicio de Pacientes.

Corresponde a la entidad "Paciente (interno del asilo)" definida en el
documento de Estructura de Capas del proyecto.
"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Sexo = Literal["M", "F"]
EstadoPaciente = Literal["ACTIVO", "EGRESADO", "FALLECIDO"]


def _validar_fecha(valor: str) -> str:
    """Acepta unicamente fechas con formato AAAA-MM-DD."""
    try:
        datetime.strptime(valor, "%Y-%m-%d")
    except ValueError:
        raise ValueError("La fecha debe tener el formato AAAA-MM-DD, por ejemplo 1945-03-12.")
    return valor


class PacienteBase(BaseModel):
    nombres: str = Field(min_length=2, max_length=80)
    apellidos: str = Field(min_length=2, max_length=80)
    dpi: Optional[str] = Field(default=None, max_length=20)
    fecha_nacimiento: str
    sexo: Sexo
    tipo_sangre: Optional[str] = Field(default=None, max_length=5)
    fecha_ingreso: str
    habitacion: Optional[str] = Field(default=None, max_length=20)
    procedencia: Optional[str] = Field(default=None, max_length=150)
    familiar_nombre: str = Field(min_length=3, max_length=120)
    familiar_parentesco: Optional[str] = Field(default=None, max_length=40)
    familiar_telefono: str = Field(min_length=8, max_length=20)
    familiar_email: Optional[str] = Field(default=None, max_length=120)
    padecimientos: Optional[str] = Field(default=None, max_length=400)
    alergias: Optional[str] = Field(default=None, max_length=200)
    cubierto_fundacion: bool = True

    @field_validator("fecha_nacimiento", "fecha_ingreso")
    @classmethod
    def formato_de_fecha(cls, valor: str) -> str:
        return _validar_fecha(valor)

    @field_validator("fecha_nacimiento")
    @classmethod
    def debe_ser_mayor(cls, valor: str) -> str:
        """El asilo unicamente recibe adultos mayores de 60 anios."""
        nacimiento = datetime.strptime(valor, "%Y-%m-%d").date()
        hoy = date.today()
        edad = hoy.year - nacimiento.year - (
            (hoy.month, hoy.day) < (nacimiento.month, nacimiento.day)
        )
        if edad < 60:
            raise ValueError(
                f"El asilo recibe personas de 60 anios o mas. La fecha indicada da {edad} anios."
            )
        if edad > 120:
            raise ValueError("Revise la fecha de nacimiento, la edad calculada no es valida.")
        return valor


class PacienteCrear(PacienteBase):
    pass


class PacienteActualizar(BaseModel):
    habitacion: Optional[str] = Field(default=None, max_length=20)
    familiar_nombre: Optional[str] = Field(default=None, min_length=3, max_length=120)
    familiar_parentesco: Optional[str] = Field(default=None, max_length=40)
    familiar_telefono: Optional[str] = Field(default=None, min_length=8, max_length=20)
    familiar_email: Optional[str] = Field(default=None, max_length=120)
    padecimientos: Optional[str] = Field(default=None, max_length=400)
    alergias: Optional[str] = Field(default=None, max_length=200)
    cubierto_fundacion: Optional[bool] = None
    estado: Optional[EstadoPaciente] = None


class Paciente(PacienteBase):
    id: int
    codigo: str
    estado: EstadoPaciente
    fecha_registro: str
    edad: int
