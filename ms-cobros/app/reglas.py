"""
Reglas de negocio del microservicio de Cobros.

Se mantienen separadas de la API (main.py) y del acceso a datos (db.py)
para respetar la separacion de capas definida en la arquitectura del
proyecto. Aqui vive el requerimiento: "calculo del costo de citas,
examenes y medicamentos aplicando el descuento otorgado por la fundacion".
"""


def calcular_montos(
    precio: float,
    cantidad: int,
    descuento_fundacion: float,
    cubierto_fundacion: bool,
) -> dict:
    """
    Calcula el monto que debe pagar el familiar por un cargo.

    Regla del asilo:
      - El monto bruto es el precio de la tarifa por la cantidad.
      - Si el paciente es beneficiario de la fundacion, se descuenta el
        porcentaje que la fundacion cubre para ese concepto.
      - Si no es beneficiario, paga el monto completo.

    Devuelve los tres montos redondeados a dos decimales para que el
    reporte de cobros cuadre en quetzales.
    """
    monto_bruto = round(precio * cantidad, 2)

    porcentaje = descuento_fundacion if cubierto_fundacion else 0.0
    descuento_aplicado = round(monto_bruto * (porcentaje / 100.0), 2)
    monto_neto = round(monto_bruto - descuento_aplicado, 2)

    return {
        "monto_bruto": monto_bruto,
        "descuento_aplicado": descuento_aplicado,
        "monto_neto": monto_neto,
    }
