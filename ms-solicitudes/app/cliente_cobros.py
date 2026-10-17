"""
Comunicacion entre microservicios.

Al convertir una solicitud en visita, le pide a ms-cobros el cargo de la
consulta con el descuento de la fundacion ya aplicado.

Si cobros no responde, la visita se registra igual y el cargo queda
pendiente (RNF-12): un microservicio no debe tumbar al otro.
"""

import os

import httpx

MS_COBROS_URL = os.getenv("MS_COBROS_URL", "http://ms-cobros:8082")
# Limite corto a proposito: en la red de Docker cobros contesta en
# milisegundos. Esperar mas acerca la respuesta al limite de 8 s del
# gateway, que mostraria un error por una visita que si quedo registrada.
TIMEOUT = 2.0


def _buscar_tarifa_de_especialista(cliente: httpx.Client) -> int | None:
    """
    Devuelve el id de la tarifa de consulta con especialista, la que
    corresponde a una remision del medico general. Si ninguna lo dice,
    devuelve la primera cita activa; None si no hay ninguna.
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
                    "La visita quedó registrada sin cargo."
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
            f"(la fundación cubrió Q{cargo['descuento_aplicado']:.2f}).",
        )
    except httpx.HTTPStatusError as error:
        return None, (
            "El servicio de cobros rechazó la operación "
            f"(código {error.response.status_code}). La visita quedó registrada."
        )
    except httpx.RequestError:
        return None, (
            "El servicio de cobros no respondió. La visita quedó registrada y el "
            "cargo deberá generarse cuando el servicio vuelva a estar disponible."
        )
