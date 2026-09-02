"""
Reglas de negocio del microservicio de Cobros.

Se mantienen separadas de la API (main.py) y del acceso a datos (db.py)
para respetar la separacion de capas definida en la arquitectura del
proyecto. Aqui vive el requerimiento: "calculo del costo de citas,
examenes y medicamentos aplicando el descuento otorgado por la fundacion".

CAMBIO IMPORTANTE FRENTE A LA VERSION ANTERIOR
-----------------------------------------------
Antes los montos se calculaban con float. El float no puede representar
exactamente valores como 0.1, asi que 0.1 + 0.2 da 0.30000000000000004.
Con un cargo suelto no se nota, pero al sumar cientos de cargos en el
reporte de cobros aparecen saldos como Q1247.9999999998.

Ahora se usa Decimal, que guarda el numero tal cual se escribio. Es lo
que se usa siempre para dinero, y hace juego con el tipo DECIMAL(10,2)
de la base de datos.
"""

from decimal import ROUND_HALF_UP, Decimal

# Dos decimales: los centavos del quetzal.
CENTAVOS = Decimal("0.01")


def a_decimal(valor) -> Decimal:
    """
    Convierte cualquier numero a Decimal de forma segura.

    Se pasa por str() a proposito. Decimal(0.1) hereda el error del
    float y da 0.1000000000000000055511151231257827, mientras que
    Decimal("0.1") da exactamente 0.1. Ese str() es lo que corta el
    problema en la frontera.
    """
    return Decimal(str(valor))


def redondear(valor: Decimal) -> Decimal:
    """
    Redondea a dos decimales con la regla comercial.

    ROUND_HALF_UP no es adorno: Python redondea por defecto "al par mas
    cercano", asi que round(2.675, 2) da 2.67 y no 2.68. En una factura
    eso es un centavo perdido que despues no cuadra.
    """
    return valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def calcular_montos(
    precio,
    cantidad: int,
    descuento_fundacion,
    cubierto_fundacion: bool,
) -> dict[str, Decimal]:
    """
    Calcula el monto que debe pagar el familiar por un cargo.

    Regla del asilo:
      - El monto bruto es el precio de la tarifa por la cantidad.
      - Si el paciente es beneficiario de la fundacion, se descuenta el
        porcentaje que la fundacion cubre para ese concepto.
      - Si no es beneficiario, paga el monto completo.

    Es una funcion pura: no toca la base de datos ni sabe que existe
    HTTP. Por eso se puede probar sola, con numeros escritos a mano.
    """
    precio = a_decimal(precio)
    porcentaje = a_decimal(descuento_fundacion) if cubierto_fundacion else Decimal("0")

    monto_bruto = redondear(precio * cantidad)
    descuento_aplicado = redondear(monto_bruto * porcentaje / Decimal("100"))
    monto_neto = redondear(monto_bruto - descuento_aplicado)

    return {
        "monto_bruto": monto_bruto,
        "descuento_aplicado": descuento_aplicado,
        "monto_neto": monto_neto,
    }
