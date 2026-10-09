"""
Conexiones directas a MySQL.

Las pruebas usan MySQL por tres motivos, y solo por esos:

  1. Comprobar lo que la API no deja ver: que los intentos fallidos se
     borraron, que la bitacora no guardo el cuerpo, que una tilde quedo
     bien guardada en la tabla y no solo en la respuesta.
  2. Probar el aislamiento (RNF-04) conectandose como cada usuario de
     servicio, que es justo lo que se quiere ver rechazado.
  3. Limpiar lo que el sistema no ofrece borrar (remisiones, visitas,
     cargos pagados) y devolver los contadores a su valor inicial.

Las contrasenas no estan escritas aqui: se leen de las variables de
entorno de los contenedores, que son la fuente de verdad del despliegue.
"""

import pymysql
from pymysql.cursors import DictCursor

ESQUEMAS = ("asilo_gateway", "asilo_pacientes", "asilo_solicitudes", "asilo_cobros")


def conectar(usuario: str, contrasena: str, esquema: str | None = None):
    return pymysql.connect(
        host="mysql",
        port=3306,
        user=usuario,
        password=contrasena,
        database=esquema,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=10,
    )


class Root:
    """Conexion de administrador, solo para verificar y limpiar."""

    def __init__(self, contrasena: str):
        self.contrasena = contrasena

    def consulta(self, sql: str, params=None) -> list[dict]:
        conexion = conectar("root", self.contrasena)
        with conexion:
            with conexion.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())

    def uno(self, sql: str, params=None):
        """Primer valor de la primera fila, o None."""
        filas = self.consulta(sql, params)
        if not filas:
            return None
        return next(iter(filas[0].values()))

    def ejecutar(self, sql: str, params=None) -> int:
        conexion = conectar("root", self.contrasena)
        with conexion:
            with conexion.cursor() as cur:
                return cur.execute(sql, params)

    def contadores(self) -> dict[str, int]:
        """
        AUTO_INCREMENT de cada tabla de los cuatro esquemas.

        information_schema guarda esos numeros en cache hasta 24 horas
        (information_schema_stats_expiry). Si no se apaga la cache para
        esta conexion, se leeria un valor viejo y la restauracion final
        dejaria el contador mal puesto.
        """
        conexion = conectar("root", self.contrasena)
        with conexion:
            with conexion.cursor() as cur:
                cur.execute("SET SESSION information_schema_stats_expiry = 0")
                cur.execute(
                    """SELECT TABLE_SCHEMA AS esquema, TABLE_NAME AS tabla,
                              AUTO_INCREMENT AS valor
                       FROM information_schema.TABLES
                       WHERE TABLE_SCHEMA IN %s AND AUTO_INCREMENT IS NOT NULL""",
                    (ESQUEMAS,),
                )
                return {f"{f['esquema']}.{f['tabla']}": int(f["valor"]) for f in cur.fetchall()}
