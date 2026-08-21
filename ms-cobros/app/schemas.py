"""
Modelos de entrada y salida del microservicio de Cobros.

Equivalen a la "Capa de Entidades o Modelos" del documento de estructura
de capas: definen que datos viajan por la API y cuales son obligatorios.
Pydantic valida automaticamente cada peticion contra estas clases.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

TipoCargo = Literal["CITA", "EXAMEN", "MEDICAMENTO"]


class TarifaBase(BaseModel):
    concepto: str = Field(min_length=3, max_length=120)
    tipo: TipoCargo
    precio: float = Field(gt=0, description="Precio en quetzales, sin descuento")
    descuento_fundacion: float = Field(
        default=0, ge=0, le=100,
        description="Porcentaje que cubre la fundacion para pacientes beneficiarios",
    )
    activo: bool = True


class TarifaCrear(TarifaBase):
    pass


class TarifaActualizar(BaseModel):
    concepto: Optional[str] = Field(default=None, min_length=3, max_length=120)
    tipo: Optional[TipoCargo] = None
    precio: Optional[float] = Field(default=None, gt=0)
    descuento_fundacion: Optional[float] = Field(default=None, ge=0, le=100)
    activo: Optional[bool] = None


class Tarifa(TarifaBase):
    id: int


class CargoCrear(BaseModel):
    paciente_id: str = Field(min_length=1, max_length=40)
    paciente_nombre: Optional[str] = None
    familiar_email: Optional[str] = None
    tipo: TipoCargo
    tarifa_id: Optional[int] = Field(
        default=None,
        description="Si no se envia, se toma la primera tarifa activa de ese tipo",
    )
    cantidad: int = Field(default=1, ge=1, le=100)
    cubierto_fundacion: bool = Field(
        default=False, description="Indica si el paciente es beneficiario de la fundacion"
    )
    referencia: Optional[str] = Field(
        default=None, description="Origen del cargo, por ejemplo VISITA-7"
    )


class Cargo(BaseModel):
    id: int
    paciente_id: str
    paciente_nombre: Optional[str]
    familiar_email: Optional[str]
    tarifa_id: int
    concepto: str
    tipo: TipoCargo
    cantidad: int
    monto_bruto: float
    descuento_aplicado: float
    monto_neto: float
    cubierto_fundacion: bool
    estado: str
    referencia: Optional[str]
    fecha: str


class EstadoCuenta(BaseModel):
    """Resumen de la cuenta que el familiar debe cancelar al asilo."""

    paciente_id: str
    paciente_nombre: Optional[str]
    familiar_email: Optional[str]
    cantidad_cargos: int
    total_bruto: float
    total_descuento_fundacion: float
    total_neto: float
    total_pagado: float
    saldo_pendiente: float
    cargos: list[Cargo]
