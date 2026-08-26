"""
Microservicio de Registro de Ancianos (Pacientes internos)
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Responsabilidad unica: llevar el registro de los ancianos internos del
asilo, sus datos personales, su familiar responsable y su estado dentro
de la institucion.

Puerto: 8083
Documentacion interactiva: http://localhost:8083/docs
"""

from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .db import get_conn, init_db, siguiente_codigo
from .schemas import Paciente, PacienteActualizar, PacienteCrear

app = FastAPI(
    title="MS Pacientes - Asilo Cabeza de Algodon",
    description="Microservicio de registro de los ancianos internos del asilo.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def al_iniciar() -> None:
    init_db()


def calcular_edad(fecha_nacimiento: str) -> int:
    nacimiento = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
    hoy = date.today()
    return hoy.year - nacimiento.year - (
        (hoy.month, hoy.day) < (nacimiento.month, nacimiento.day)
    )


def fila_a_paciente(fila) -> dict:
    paciente = dict(fila)
    paciente["cubierto_fundacion"] = bool(paciente["cubierto_fundacion"])
    paciente["edad"] = calcular_edad(paciente["fecha_nacimiento"])
    return paciente


@app.get("/health", tags=["Estado"])
def health() -> dict:
    conn = get_conn()
    activos = conn.execute(
        "SELECT COUNT(*) AS n FROM pacientes WHERE estado = 'ACTIVO'"
    ).fetchone()["n"]
    conn.close()
    return {"servicio": "ms-pacientes", "estado": "arriba", "ancianos_activos": activos}


@app.post("/pacientes", response_model=Paciente, status_code=201, tags=["Pacientes"])
def registrar_paciente(datos: PacienteCrear):
    """Da de alta a un anciano en el asilo y le asigna su codigo correlativo."""
    if datos.fecha_ingreso < datos.fecha_nacimiento:
        raise HTTPException(
            status_code=422,
            detail="La fecha de ingreso no puede ser anterior a la fecha de nacimiento.",
        )

    conn = get_conn()
    if datos.dpi:
        repetido = conn.execute(
            "SELECT codigo FROM pacientes WHERE dpi = ?", (datos.dpi,)
        ).fetchone()
        if repetido:
            conn.close()
            raise HTTPException(
                status_code=409,
                detail=f"Ese DPI ya esta registrado con el codigo {repetido['codigo']}.",
            )

    with conn:
        codigo = siguiente_codigo(conn)
        cursor = conn.execute(
            """INSERT INTO pacientes (
                   codigo, nombres, apellidos, dpi, fecha_nacimiento, sexo, tipo_sangre,
                   fecha_ingreso, habitacion, procedencia, familiar_nombre,
                   familiar_parentesco, familiar_telefono, familiar_email, padecimientos,
                   alergias, cubierto_fundacion, estado, fecha_registro)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVO', ?)""",
            (
                codigo,
                datos.nombres.strip(),
                datos.apellidos.strip(),
                datos.dpi,
                datos.fecha_nacimiento,
                datos.sexo,
                datos.tipo_sangre,
                datos.fecha_ingreso,
                datos.habitacion,
                datos.procedencia,
                datos.familiar_nombre.strip(),
                datos.familiar_parentesco,
                datos.familiar_telefono,
                datos.familiar_email,
                datos.padecimientos,
                datos.alergias,
                int(datos.cubierto_fundacion),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        fila = conn.execute(
            "SELECT * FROM pacientes WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    conn.close()
    return fila_a_paciente(fila)


@app.get("/pacientes", response_model=list[Paciente], tags=["Pacientes"])
def listar_pacientes(
    estado: str | None = Query(default=None, description="ACTIVO, EGRESADO o FALLECIDO"),
    buscar: str | None = Query(default=None, description="Busca por nombre, apellido o codigo"),
):
    sql = "SELECT * FROM pacientes WHERE 1 = 1"
    params: list = []
    if estado:
        sql += " AND estado = ?"
        params.append(estado.upper())
    if buscar:
        sql += " AND (nombres LIKE ? OR apellidos LIKE ? OR codigo LIKE ?)"
        patron = f"%{buscar}%"
        params.extend([patron, patron, patron])
    sql += " ORDER BY id DESC"

    conn = get_conn()
    filas = conn.execute(sql, params).fetchall()
    conn.close()
    return [fila_a_paciente(f) for f in filas]


@app.get("/pacientes/{codigo}", response_model=Paciente, tags=["Pacientes"])
def obtener_paciente(codigo: str):
    conn = get_conn()
    fila = conn.execute("SELECT * FROM pacientes WHERE codigo = ?", (codigo,)).fetchone()
    conn.close()
    if fila is None:
        raise HTTPException(status_code=404, detail="No existe un anciano con ese codigo.")
    return fila_a_paciente(fila)


@app.put("/pacientes/{codigo}", response_model=Paciente, tags=["Pacientes"])
def actualizar_paciente(codigo: str, datos: PacienteActualizar):
    """Actualiza los datos que si pueden cambiar durante la estadia."""
    cambios = datos.model_dump(exclude_unset=True)
    if not cambios:
        raise HTTPException(status_code=400, detail="No se enviaron campos por actualizar.")
    if "cubierto_fundacion" in cambios:
        cambios["cubierto_fundacion"] = int(cambios["cubierto_fundacion"])

    conn = get_conn()
    existe = conn.execute(
        "SELECT id FROM pacientes WHERE codigo = ?", (codigo,)
    ).fetchone()
    if existe is None:
        conn.close()
        raise HTTPException(status_code=404, detail="No existe un anciano con ese codigo.")

    asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)
    with conn:
        conn.execute(
            f"UPDATE pacientes SET {asignaciones} WHERE codigo = ?",
            [*cambios.values(), codigo],
        )
        fila = conn.execute(
            "SELECT * FROM pacientes WHERE codigo = ?", (codigo,)
        ).fetchone()
    conn.close()
    return fila_a_paciente(fila)


@app.delete("/pacientes/{codigo}", status_code=204, tags=["Pacientes"])
def eliminar_paciente(codigo: str):
    """
    Elimina el registro de un anciano.

    Nota: en produccion conviene marcarlo como EGRESADO en lugar de
    borrarlo, para conservar su historial medico.
    """
    conn = get_conn()
    existe = conn.execute(
        "SELECT id FROM pacientes WHERE codigo = ?", (codigo,)
    ).fetchone()
    if existe is None:
        conn.close()
        raise HTTPException(status_code=404, detail="No existe un anciano con ese codigo.")
    with conn:
        conn.execute("DELETE FROM pacientes WHERE codigo = ?", (codigo,))
    conn.close()
