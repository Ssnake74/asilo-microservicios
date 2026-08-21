"""
Modelos de entrada y salida del microservicio de Solicitudes.

Reflejan las entidades "Solicitud de Consulta" y "Visita Medica" definidas
en el documento de Estructura de Capas del proyecto.
"""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class SolicitudCrear(BaseModel):
    paciente_id: str = Field(min_length=1, max_length=40)
    paciente_nombre: str = Field(min_length=3, max_length=120)
    familiar_email: Optional[EmailStr] = Field(
        default=None, description="Correo al que se notifica la solicitud"
    )
    medico_general: str = Field(min_length=3, max_length=120)
    especialidad_remitida: str = Field(
        min_length=3, max_length=60,
        description="Especialidad a la que el medico general remite al paciente",
    )
    motivo: str = Field(min_length=5, max_length=400)
    cubierto_fundacion: bool = Field(
        default=True, description="El paciente recibe el descuento de la fundacion"
    )


class Solicitud(BaseModel):
    id: int
    paciente_id: str
    paciente_nombre: str
    familiar_email: Optional[str]
    medico_general: str
    especialidad_remitida: str
    motivo: str
    cubierto_fundacion: bool
    estado: str
    fecha_solicitud: str


class ConversionSolicitud(BaseModel):
    """Datos que la fundacion agrega al asignar la visita medica formal."""

    medico_tratante: str = Field(min_length=3, max_length=120)
    especialidad: str = Field(min_length=3, max_length=60)
    fecha_visita: str = Field(
        min_length=8, max_length=25, description="Fecha y hora asignada, formato AAAA-MM-DD HH:MM"
    )
    observaciones: Optional[str] = Field(default=None, max_length=400)


class Visita(BaseModel):
    id: int
    solicitud_id: int
    paciente_id: str
    paciente_nombre: str
    medico_tratante: str
    especialidad: str
    fecha_visita: str
    observaciones: Optional[str]
    cargo_id: Optional[int]
    cargo_generado: bool


class VisitaCreada(BaseModel):
    """Respuesta de la conversion: la visita y el aviso del cobro asociado."""

    visita: Visita
    solicitud: Solicitud
    mensaje_cobro: str
