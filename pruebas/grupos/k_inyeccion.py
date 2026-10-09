"""
K · Inyeccion y validacion (RNF-05)

Texto con comillas, punto y coma y sentencias SQL debe guardarse como
TEXTO, letra por letra, y las tablas deben seguir existiendo despues.
Si alguna consulta concatenara valores en vez de usar parametros, aqui
se veria: o fallaria el guardado, o cambiaria el texto, o desapareceria
una tabla.
"""

from apoyo.gateway import resumen

LETRA = "K"
TITULO = "Inyección y validación"
DESCRIPCION = (
    "Textos maliciosos guardados literalmente, búsquedas con inyección, campos "
    "fuera de rango y actualización con campos no permitidos."
)


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw

    with rep.caso(
        "Textos con comillas, punto y coma y DROP TABLE se guardan literalmente",
        "RNF-05",
        "201, y el texto vuelve idéntico por la API y está idéntico en MySQL; las "
        "tablas siguen existiendo",
    ) as c:
        maliciosos = {
            "nombres": "O'Brien; DROP TABLE pacientes; --",
            "familiar_nombre": 'Ana "la jefa" \\ \' OR \'1\'=\'1',
            "padecimientos": "'); DELETE FROM pacientes WHERE ('1'='1",
        }
        r, ficha = ctx.crear_interno("K Robert'); DROP TABLE pacientes;--", **maliciosos)
        if r.status_code != 201:
            c.obtenido = resumen(r)
        else:
            codigo = r.json()["codigo"]
            api = gw.get("SECRETARIA", f"/api/pacientes/{codigo}").json()
            fila = ctx.root.consulta(
                """SELECT nombres, apellidos, familiar_nombre, padecimientos
                   FROM asilo_pacientes.pacientes WHERE codigo = %s""",
                (codigo,),
            )[0]
            remision = ctx.crear_remision(api, "Geriatria", etiqueta="'); DROP TABLE solicitudes; --")
            motivo_ok = remision.status_code == 201 and remision.json()["motivo"].endswith(
                "'); DROP TABLE solicitudes; --"
            )
            tablas = ctx.root.uno(
                """SELECT COUNT(*) FROM information_schema.TABLES
                   WHERE (TABLE_SCHEMA, TABLE_NAME) IN
                         (('asilo_pacientes', 'pacientes'), ('asilo_solicitudes', 'solicitudes'))"""
            )
            campos = list(maliciosos) + ["apellidos"]
            alterados = [k for k in campos if api.get(k) != ficha[k] or fila.get(k) != ficha[k]]
            c.obtenido = (
                f"{codigo} · nombres «{fila['nombres']}» · familiar «{fila['familiar_nombre']}» · "
                f"remisión con motivo malicioso: {remision.status_code} "
                f"({'guardado igual' if motivo_ok else 'ALTERADO'}) · tablas pacientes y "
                f"solicitudes presentes: {tablas} de 2"
            )
            if alterados:
                c.obtenido += f" · campos alterados: {', '.join(alterados)}"
            c.pasa = not alterados and motivo_ok and tablas == 2

    with rep.caso(
        "Búsquedas con inyección en el filtro",
        "RNF-05",
        "200 y el filtro se trata como texto: «' OR '1'='1» no devuelve todos los "
        "internos ni toda la bitácora",
    ) as c:
        ataque = "' OR '1'='1"
        todos = len(gw.get("ADMIN", "/api/pacientes").json())
        internos = gw.get("ADMIN", "/api/pacientes", params={"buscar": ataque})
        bitacora = gw.get("ADMIN", "/api/bitacora", params={"usuario": ataque})
        n_int = len(internos.json()) if internos.status_code == 200 else None
        n_bit = len(bitacora.json()) if bitacora.status_code == 200 else None
        c.obtenido = (
            f"/api/pacientes?buscar=…: {internos.status_code}, {n_int} resultado(s) de {todos} "
            f"internos · /api/bitacora?usuario=…: {bitacora.status_code}, {n_bit} fila(s)"
        )
        c.pasa = internos.status_code == 200 and bitacora.status_code == 200 and n_int == 0 and n_bit == 0

    with rep.caso(
        "Campos fuera de rango",
        "Validación de entrada (CU-03 y CU-06)",
        "422 en cada uno de los envíos inválidos",
    ) as c:
        envios = [
            ("nombres de 1 letra", "pacientes", {"nombres": "A"}),
            ("nombres de 81 letras", "pacientes", {"nombres": "A" * 81}),
            ("sexo «X»", "pacientes", {"sexo": "X"}),
            ("teléfono de 4 dígitos", "pacientes", {"familiar_telefono": "1234"}),
            ("DPI de 21 caracteres", "pacientes", {"dpi": "1" * 21}),
            ("fecha «12/03/1945»", "pacientes", {"fecha_nacimiento": "12/03/1945"}),
            ("tipo de sangre de 6 caracteres", "pacientes", {"tipo_sangre": "ABCDEF"}),
            ("motivo de 4 letras", "solicitudes", {"motivo": "dolo"}),
            ("correo sin arroba", "solicitudes", {"familiar_email": "familia.example.com"}),
        ]
        base_remision = {
            "paciente_id": "PAC-000", "paciente_nombre": f"{ctx.marca} K", "familiar_email": None,
            "medico_general": "Dr. Luis Marroquín", "especialidad_remitida": "Geriatria",
            "motivo": f"{ctx.marca} K", "cubierto_fundacion": True,
        }
        lineas, todos_422 = [], True
        for descripcion, recurso, cambio in envios:
            if recurso == "pacientes":
                cuerpo = ctx.ficha_interno("K rango", **cambio)
                r = gw.post("SECRETARIA", "/api/pacientes", json=cuerpo)
                if r.status_code == 201:
                    ctx.creados["pacientes"].append(r.json()["codigo"])
            else:
                r = gw.post("MEDICO_GENERAL", "/api/solicitudes", json={**base_remision, **cambio})
                if r.status_code == 201:
                    ctx.creados["solicitudes"].append(r.json()["id"])
            lineas.append(f"{descripcion}: {r.status_code}")
            todos_422 &= r.status_code == 422
        rechazados = sum(1 for linea in lineas if linea.endswith("422"))
        c.obtenido = f"{rechazados} de {len(envios)} rechazados con 422\n" + " · ".join(lineas)
        c.pasa = todos_422

    with rep.caso(
        "Actualización con campos no permitidos",
        "RNF-05 (lista blanca del UPDATE)",
        "200: se aplica la habitación y se descartan nombres, DPI, fecha de "
        "nacimiento, código e id",
    ) as c:
        interno = ctx.interno("K actualizar")
        codigo = interno["codigo"]
        r = gw.put(
            "SECRETARIA", f"/api/pacientes/{codigo}",
            json={"habitacion": "K-7", "nombres": "Cambiado", "dpi": "1111111111111",
                  "fecha_nacimiento": "1990-01-01", "codigo": "PAC-000", "id": 1},
        )
        fila = ctx.root.consulta(
            """SELECT codigo, nombres, dpi, fecha_nacimiento, habitacion
               FROM asilo_pacientes.pacientes WHERE id = %s""",
            (interno["id"],),
        )[0]
        sin_cambio = (
            fila["codigo"] == codigo and fila["nombres"] == interno["nombres"]
            and fila["dpi"] == interno["dpi"] and str(fila["fecha_nacimiento"]) == interno["fecha_nacimiento"]
        )
        c.obtenido = (
            f"{r.status_code} · en la base: código {fila['codigo']}, nombres «{fila['nombres']}», "
            f"DPI {fila['dpi']}, nacimiento {fila['fecha_nacimiento']}, habitación {fila['habitacion']}"
        )
        c.pasa = r.status_code == 200 and fila["habitacion"] == "K-7" and sin_cambio
