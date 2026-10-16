"""Modelos de entrada y salida del microservicio de Catalogo."""

from typing import Optional

from pydantic import BaseModel, Field


class EspecialidadCrear(BaseModel):
    nombre: str = Field(min_length=3, max_length=60)


class EspecialidadActualizar(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=3, max_length=60)
    activo: Optional[bool] = None


class Especialidad(BaseModel):
    id: int
    nombre: str
    activo: bool


class MedicoCrear(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)
    colegiado: Optional[str] = Field(default=None, max_length=20)
    especialidad_id: int


class MedicoActualizar(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=3, max_length=120)
    colegiado: Optional[str] = Field(default=None, max_length=20)
    especialidad_id: Optional[int] = None
    activo: Optional[bool] = None


class Medico(BaseModel):
    id: int
    nombre: str
    colegiado: Optional[str]
    especialidad_id: int
    especialidad: str
    activo: bool


class EnfermeroCrear(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)


class EnfermeroActualizar(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=3, max_length=120)
    activo: Optional[bool] = None


class Enfermero(BaseModel):
    id: int
    nombre: str
    activo: bool


class ExamenCrear(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)
    tarifa_id: Optional[int] = Field(
        default=None, description="Concepto del tarifario con que se cobra el examen"
    )


class ExamenActualizar(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=3, max_length=120)
    tarifa_id: Optional[int] = None
    activo: Optional[bool] = None


class Examen(BaseModel):
    id: int
    nombre: str
    tarifa_id: Optional[int]
    activo: bool


class MedicamentoCrear(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)
    presentacion: Optional[str] = Field(default=None, max_length=80)
    tarifa_id: Optional[int] = Field(
        default=None, description="Concepto del tarifario con que se cobra el medicamento"
    )


class MedicamentoActualizar(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=3, max_length=120)
    presentacion: Optional[str] = Field(default=None, max_length=80)
    tarifa_id: Optional[int] = None
    activo: Optional[bool] = None


class Medicamento(BaseModel):
    id: int
    nombre: str
    presentacion: Optional[str]
    tarifa_id: Optional[int]
    activo: bool
