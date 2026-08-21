# Microservicios — Sistema para Administración Asilo de Ancianos «Cabeza de Algodón»

**Universidad Mariano Gálvez de Guatemala** · Centro Regional de Mazatenango
Análisis y Diseño de Sistemas II · Ing. Angel Atilio Maltez C.
Estudiante: Julio César Sagastume Villavicencio · Carné: 3090 23 18018

---

## 1. Qué se construyó

Dos microservicios independientes, tomados directamente de las reglas de negocio
definidas en los documentos de **Arquitectura** y **Estructura de Capas** del proyecto,
más una **aplicación base** que los consume desde el navegador.

| Microservicio | Puerto | Responsabilidad |
|---|---|---|
| `ms-solicitudes` | 8081 | Registra las solicitudes de consulta del médico general y las **convierte en visitas médicas formales**, validando médico tratante y especialidad. |
| `ms-cobros` | 8082 | Administra el **tarifario**, genera los cargos de citas, exámenes y medicamentos **aplicando el descuento de la fundación**, y lleva el estado de cuenta del familiar. |
| `app-base` | 8080 | Aplicación web (HTML + JavaScript) que consume ambos microservicios y muestra en vivo cada llamada HTTP. |

Cada microservicio tiene **su propia base de datos SQLite** (patrón *database per service*),
su propio `Dockerfile` y su propia documentación interactiva generada por FastAPI.

### Cómo se comunican

```
Navegador (app-base :8080)
        │
        ├── HTTP ──► ms-solicitudes :8081 ──┐
        │                                    │ HTTP interno
        └── HTTP ──► ms-cobros      :8082 ◄──┘
```

Al confirmar una visita médica, `ms-solicitudes` llama por HTTP a `ms-cobros` para
generar el cargo de la consulta. Si `ms-cobros` está apagado, la visita **se registra
igual** y queda marcada como "cargo pendiente de generar": un servicio no tumba al otro.

---

## 2. Requisitos

- **Docker Desktop** (incluye Docker Compose), o
- **Python 3.11 o superior** si se prefiere ejecutar sin contenedores.

---

## 3. Ejecución con Docker (forma recomendada)

Desde la carpeta `asilo-microservicios/`:

```bash
docker compose up --build
```

Luego abrir en el navegador:

| Dirección | Qué es |
|---|---|
| http://localhost:8080 | Aplicación base |
| http://localhost:8081/docs | Documentación Swagger de `ms-solicitudes` |
| http://localhost:8082/docs | Documentación Swagger de `ms-cobros` |

Para detener todo: `Ctrl + C` y luego `docker compose down`.
Para borrar también las bases de datos: `docker compose down -v`.

Comandos útiles durante la grabación del video:

```bash
docker compose ps                    # muestra los tres contenedores corriendo
docker compose logs -f ms-cobros     # muestra en vivo las peticiones que recibe
docker compose stop ms-cobros        # apaga un servicio para demostrar la tolerancia a fallos
docker compose start ms-cobros       # lo vuelve a levantar
```

---

## 4. Ejecución sin Docker

En tres terminales distintas:

```bash
# Terminal 1
cd ms-cobros
pip install -r requirements.txt
uvicorn app.main:app --port 8082 --reload

# Terminal 2
cd ms-solicitudes
pip install -r requirements.txt
uvicorn app.main:app --port 8081 --reload

# Terminal 3
cd app-base
python -m http.server 8080
```

---

## 5. Endpoints

### `ms-solicitudes` (8081)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Estado del servicio |
| POST | `/solicitudes` | Registra la solicitud del médico general |
| GET | `/solicitudes` | Lista solicitudes (filtros `estado`, `paciente_id`) |
| GET | `/solicitudes/{id}` | Consulta una solicitud |
| DELETE | `/solicitudes/{id}` | Anula una solicitud pendiente |
| **POST** | **`/solicitudes/{id}/convertir`** | **Convierte la solicitud en visita médica formal** |
| GET | `/visitas` | Lista las visitas médicas |
| GET | `/visitas/{id}` | Consulta una visita |

**Validaciones de la conversión:** la solicitud debe existir, debe estar en estado
`PENDIENTE`, debe indicarse médico tratante y la especialidad asignada debe coincidir
con la que remitió el médico general. Si no coincide, el servicio responde `422` con
el detalle del error.

### `ms-cobros` (8082)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Estado del servicio |
| GET/POST | `/tarifas` | Lista y crea tarifas |
| GET/PUT/DELETE | `/tarifas/{id}` | Consulta, actualiza y elimina una tarifa |
| POST | `/cargos` | Genera un cargo aplicando el descuento de la fundación |
| GET | `/cargos` | Lista cargos (filtros `paciente_id`, `estado`) |
| POST | `/cargos/{id}/pagar` | Registra el pago del familiar |
| DELETE | `/cargos/{id}` | Anula un cargo no pagado |
| GET | `/estado-cuenta/{paciente_id}` | Corte de cuenta con totales y saldo |

**Regla del descuento** (`ms-cobros/app/reglas.py`):

```
monto_bruto  = precio de la tarifa × cantidad
descuento    = monto_bruto × (porcentaje que cubre la fundación / 100)   [solo si el paciente es beneficiario]
monto_neto   = monto_bruto − descuento     ← lo que paga el familiar
```

---

## 6. Prueba rápida desde la terminal

```bash
# 1. Crear una solicitud
curl -X POST http://localhost:8081/solicitudes \
  -H "Content-Type: application/json" \
  -d '{"paciente_id":"PAC-001","paciente_nombre":"Rosa Elena Coronado","familiar_email":"familiar@correo.com","medico_general":"Dr. Luis Marroquin","especialidad_remitida":"Cardiologia","motivo":"Presion arterial elevada","cubierto_fundacion":true}'

# 2. Intentar convertirla con la especialidad equivocada (debe fallar con 422)
curl -X POST http://localhost:8081/solicitudes/1/convertir \
  -H "Content-Type: application/json" \
  -d '{"medico_tratante":"Dra. Ana Sical","especialidad":"Dermatologia","fecha_visita":"2026-08-25 09:30"}'

# 3. Convertirla correctamente (genera el cargo en ms-cobros)
curl -X POST http://localhost:8081/solicitudes/1/convertir \
  -H "Content-Type: application/json" \
  -d '{"medico_tratante":"Dra. Ana Sical","especialidad":"Cardiologia","fecha_visita":"2026-08-25 09:30"}'

# 4. Ver el estado de cuenta del familiar
curl http://localhost:8082/estado-cuenta/PAC-001
```

---

## 7. Estructura de archivos

```
asilo-microservicios/
├── docker-compose.yml          Orquesta los tres contenedores
├── README.md
├── GUION_VIDEO.md              Guion sugerido para la grabación
│
├── ms-solicitudes/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             API y regla de conversión a visita médica
│       ├── schemas.py          Entidades y validaciones de entrada
│       ├── db.py               Acceso a datos (SQLite)
│       └── cliente_cobros.py   Llamada HTTP al otro microservicio
│
├── ms-cobros/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             API de tarifas, cargos y estado de cuenta
│       ├── reglas.py           Cálculo del descuento de la fundación
│       ├── schemas.py
│       └── db.py
│
└── app-base/
    ├── Dockerfile              Nginx sirviendo la página
    └── index.html              Aplicación base que consume ambos servicios
```

---

## 8. Relación con los documentos entregados

| Documento previo | Cómo se refleja aquí |
|---|---|
| Arquitectura en tres capas | Cada microservicio conserva sus capas: API (presentación/controlador), reglas de negocio y acceso a datos. |
| Capa de lógica de negocio | `reglas.py` (descuento de la fundación) y la conversión de solicitud a visita en `main.py`. |
| Capa de acceso a datos (Repositorio) | `db.py` es lo único que toca la base de datos. |
| Capa de entidades o modelos | `schemas.py` define Solicitud, Visita Médica, Tarifa y Cargo. |
| Base de datos relacional | SQLite en esta demostración; el mismo diseño de tablas migra a MySQL, SQL Server u Oracle en el servidor de la universidad. |
