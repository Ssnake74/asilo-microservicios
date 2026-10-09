"""
J · Aislamiento de datos (RNF-04)

Cada microservicio entra a MySQL con su propio usuario, y ese usuario
solo tiene permiso sobre su esquema. Aqui se comprueba que esa regla la
impone el MOTOR: se conecta como cada usuario de servicio y se intenta
entrar a los esquemas ajenos. MySQL debe responder "Access denied".

Las credenciales de los cuatro usuarios en uso se leen de las variables
de entorno de cada contenedor. Las de u_catalogo y u_clinico, que estan
reservados para modulos futuros, salen del script de creacion de MySQL.
"""

import re

import pymysql

from apoyo.base_datos import conectar

LETRA = "J"
TITULO = "Aislamiento de datos"
DESCRIPCION = "Cada usuario de servicio de MySQL ve solo su esquema y recibe «Access denied» en los ajenos."

# (usuario, esquema propio, contenedor del que se lee la contrasena o None)
USUARIOS = [
    ("u_cobros", "asilo_cobros", "asilo-ms-cobros"),
    ("u_pacientes", "asilo_pacientes", "asilo-ms-pacientes"),
    ("u_solicitudes", "asilo_solicitudes", "asilo-ms-solicitudes"),
    ("u_gateway", "asilo_gateway", "asilo-gateway"),
    ("u_catalogo", "asilo_catalogo", None),
    ("u_clinico", "asilo_clinico", None),
]

ESQUEMAS = [esquema for _, esquema, _ in USUARIOS]

# Una tabla real de cada esquema, para intentar leerla desde fuera.
TABLA = {
    "asilo_cobros": "cargos",
    "asilo_pacientes": "pacientes",
    "asilo_solicitudes": "solicitudes",
    "asilo_gateway": "usuarios",
}

INVISIBLES = {"information_schema", "performance_schema"}


def contrasenas_del_script() -> dict[str, str]:
    try:
        with open("/init-sql/01-esquemas.sql", encoding="utf-8") as archivo:
            texto = archivo.read()
    except OSError:
        return {}
    return dict(re.findall(r"CREATE USER IF NOT EXISTS '(\w+)'@'%'\s+IDENTIFIED BY '([^']+)'", texto))


def intentar(conexion, sql: str) -> str:
    """'permitido' o el error que devuelve MySQL, abreviado."""
    try:
        with conexion.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()
        return "permitido"
    except pymysql.MySQLError as error:
        codigo, mensaje = error.args[0], str(error.args[1]) if len(error.args) > 1 else str(error)
        return f"{codigo} {mensaje.split(' to ')[0].split(' for ')[0]}"


def ejecutar(ctx) -> None:
    rep, docker = ctx.rep, ctx.docker
    del_script = contrasenas_del_script()

    for usuario, propio, contenedor in USUARIOS:
        if contenedor:
            entorno = docker.variables(contenedor)
            contrasena = entorno.get("DB_PASSWORD")
            origen = f"variables de {contenedor}"
        else:
            contrasena = del_script.get(usuario)
            origen = "script 01-esquemas.sql (usuario reservado)"

        with rep.caso(
            f"{usuario} solo ve su esquema y no entra a los ajenos",
            "RNF-04",
            f"SHOW DATABASES muestra solo {propio}; USE y SELECT sobre cada esquema "
            "ajeno dan «Access denied» (1044) o «command denied» (1142)",
        ) as c:
            if not contrasena:
                raise RuntimeError(f"no se encontró la contraseña de {usuario} ({origen})")
            conexion = conectar(usuario, contrasena)
            with conexion:
                with conexion.cursor() as cur:
                    cur.execute("SHOW DATABASES")
                    visibles = sorted(
                        f["Database"] for f in cur.fetchall() if f["Database"] not in INVISIBLES
                    )
                lineas = [f"ve: {', '.join(visibles) or '(nada)'}"]
                todo_negado = True
                for ajeno in ESQUEMAS:
                    if ajeno == propio:
                        continue
                    uso = intentar(conexion, f"USE `{ajeno}`")
                    lectura = ""
                    if ajeno in TABLA:
                        lectura = intentar(conexion, f"SELECT * FROM `{ajeno}`.`{TABLA[ajeno]}` LIMIT 1")
                    lineas.append(
                        f"{ajeno}: USE → {uso}" + (f" · SELECT {TABLA[ajeno]} → {lectura}" if lectura else "")
                    )
                    todo_negado &= uso != "permitido" and lectura != "permitido"
                    todo_negado &= uso.startswith("1044") and (not lectura or lectura.startswith("1142"))
            c.obtenido = "\n".join(lineas)
            c.pasa = visibles == [propio] and todo_negado
