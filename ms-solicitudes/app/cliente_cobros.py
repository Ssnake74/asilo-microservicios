"""
Comunicacion entre microservicios.

Cuando una solicitud se convierte en visita medica formal, este modulo le
pide al microservicio de Cobros que genere el cargo de la consulta con el
descuento de la fundacion ya aplicado.

La llamada es HTTP y tolerante a fallos: si el microservicio de Cobros no
responde, la visita medica se registra igual y queda marcada para generar
el cobro despues. Un microservicio no debe tumbar al otro.
"""

import os

import httpx

MS_COBROS_URL = os.getenv("MS_COBROS_URL", "http://localhost:8082")
TIMEOUT = 5.0


def _buscar_tarifa_de_especialista(cliente: httpx.Client) -> int | None:
    """
    Consulta el tarifario del MS de Cobros y devuelve el id de la tarifa de
    consulta con especialista, que es la que corresponde a una solicitud
    remitida por el medico general.
    """
    respuesta = cliente.get(
        f"{MS_COBROS_URL}/tarifas", params={"tipo": "CITA", "solo_activas": True}
    )
    respuesta.raise_for_status()
    tarifas = respuesta.json()
    if not tarifas:
        return None

    for tarifa in tarifas:
        if "especialista" in tarifa["concepto"].lower():
            return tarifa["id"]
    return tarifas[0]["id"]


def generar_cargo_consulta(
    paciente_id: str,
    paciente_nombre: str,
    familiar_email: str | None,
    cubierto_fundacion: bool,
    referencia: str,
) -> tuple[int | None, str]:
    """
    Solicita al MS de Cobros el cargo de la cita con especialista.

    Devuelve (id_del_cargo, mensaje). Si algo falla, el id es None y el
    mensaje explica por que, para mostrarlo en la aplicacion base.
    """
    try:
        with httpx.Client(timeout=TIMEOUT) as cliente:
            tarifa_id = _buscar_tarifa_de_especialista(cliente)
            if tarifa_id is None:
                return None, (
                    "No hay tarifas de consulta activas en el tarifario. "
                    "La visita quedo registrada sin cargo."
                )

            cuerpo = {
                "paciente_id": paciente_id,
                "paciente_nombre": paciente_nombre,
                "familiar_email": familiar_email,
                "tipo": "CITA",
                "tarifa_id": tarifa_id,
                "cantidad": 1,
                "cubierto_fundacion": cubierto_fundacion,
                "referencia": referencia,
            }
            respuesta = cliente.post(f"{MS_COBROS_URL}/cargos", json=cuerpo)
            respuesta.raise_for_status()
            cargo = respuesta.json()

        return (
            cargo["id"],
            f"Cargo {cargo['id']} generado por Q{cargo['monto_neto']:.2f} "
            f"(la fundacion cubrio Q{cargo['descuento_aplicado']:.2f}).",
        )
    except httpx.HTTPStatusError as error:
        return None, (
            "El servicio de cobros rechazo la operacion "
            f"(codigo {error.response.status_code}). La visita quedo registrada."
        )
    except httpx.RequestError:
        return None, (
            "El servicio de cobros no respondio. La visita quedo registrada y el "
            "cargo debera generarse cuando el servicio vuelva a estar disponible."
        )
