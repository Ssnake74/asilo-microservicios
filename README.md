# Sistema para Administración del Asilo de Ancianos «Cabeza de Algodón»

**Universidad Mariano Gálvez de Guatemala** · Centro Regional de Mazatenango
Análisis y Diseño de Sistemas II · Ing. Angel Atilio Maltez C.
Estudiante: Julio César Sagastume Villavicencio · Carné: 3090 23 18018

Sistema web que lleva el registro de los internos del asilo, sus remisiones a los
especialistas de la fundación, las visitas médicas y la cuenta de cada familiar.

---

## 1. Arquitectura

Microservicios en FastAPI (Python 3.12) detrás de un gateway, con MySQL 8, todo
sobre Docker Compose.

```
Navegador ──► gateway :8080 ──┬──► ms-pacientes
                              ├──► ms-solicitudes ──► ms-cobros
                              └──► ms-cobros

MySQL 8: un esquema y un usuario por servicio
```

| Servicio | Responsabilidad |
|---|---|
| `gateway` | Sirve las pantallas, abre la sesión, decide qué puede hacer cada rol, reenvía la petición al servicio que corresponde y lleva la bitácora. |
| `ms-pacientes` | Registro de los internos y de su familiar responsable. |
| `ms-solicitudes` | Remisiones del médico general y su conversión en visita médica. Avisa por correo al familiar. |
| `ms-cobros` | Tarifario, cargos con el descuento de la fundación y estado de cuenta. |

- El gateway es la única entrada: los microservicios no publican puerto (RNF-03).
- Cada servicio entra a MySQL con su propio usuario y solo ve su esquema. Lo impone
  el motor, no el código (RNF-04).
- Si `ms-cobros` no responde, la visita se registra igual y queda pendiente de cobro
  (RNF-12).

---

## 2. Cómo levantarlo

Requisito: Docker Desktop.

```bash
docker compose up -d --build
```

| Dirección | Qué es |
|---|---|
| http://localhost:8080 | El sistema |
| http://localhost:8091 | Adminer, para ver las tablas (solo desarrollo) |
| http://localhost:8025 | Mailpit, la bandeja con los correos que envía el sistema (solo desarrollo) |

MySQL queda además en el puerto 3307 del equipo, para conectarse con un cliente.

Para apagar: `docker compose down`. No use `docker compose down -v`: borra los datos.

---

## 3. Usuarios de demostración

| Usuario | Rol | Qué hace |
|---|---|---|
| `admin` | Administrador | Todo, y consulta la bitácora |
| `secretaria` | Secretaria del asilo | Registra a los internos y a sus familiares |
| `medico` | Médico general | Remite al interno a una especialidad |
| `fundacion` | Fundación | Asigna horario y médico, y convierte la remisión en visita |
| `caja` | Caja y cobros | Tarifario, cobros y estado de cuenta |

Contraseña de todos en desarrollo: `asilo2026`. Cinco intentos fallidos en quince
minutos bloquean al usuario.

---

## 4. Estructura

```
app-base/        Pantallas: HTML, CSS y JavaScript sin framework. Las sirve el gateway
gateway/         app/  main.py · seguridad.py · db.py · schemas.py
ms-pacientes/    app/  main.py · reglas.py · db.py · schemas.py
ms-solicitudes/  app/  los mismos, más cliente_cobros.py y notificaciones.py
ms-cobros/       app/  main.py · reglas.py · db.py · schemas.py
infra/mysql/init/01-esquemas.sql   Esquemas y usuarios de MySQL
pruebas/         Pruebas automatizadas y su reporte
docker-compose.yml
```

Cada microservicio separa cuatro capas (RNF-19 y RNF-20):

| Archivo | Capa |
|---|---|
| `main.py` | Presentación: las rutas HTTP |
| `reglas.py` | Reglas de negocio |
| `db.py` | Acceso a datos: todo el SQL del servicio |
| `schemas.py` | Entidades y validación de la entrada |

---

## 5. Rutas

Todas entran por el gateway.

| Ruta | Quién la atiende |
|---|---|
| `/api/login`, `/api/logout`, `/api/yo` | gateway: sesión |
| `/api/salud` | gateway: estado de los servicios |
| `/api/bitacora` | gateway: bitácora, solo para el administrador |
| `/api/pacientes` | `ms-pacientes` |
| `/api/solicitudes`, `/api/visitas` | `ms-solicitudes` |
| `/api/tarifas`, `/api/cargos`, `/api/estado-cuenta` | `ms-cobros` |

Qué rol puede usar cada ruta está en la tabla `PERMISOS` de
`gateway/app/seguridad.py`. Lo que no aparece ahí se niega.

---

## 6. Pruebas

Con el sistema levantado, desde la raíz del repositorio:

```powershell
powershell -ExecutionPolicy Bypass -File .\pruebas\ejecutar.ps1
```

Son 169 casos en 14 grupos, cada uno ligado al requisito que verifica. El reporte
queda en `pruebas/resultado.txt` y lista los casos que fallan y los pendientes
conocidos.

---

## 7. Estado

**Construido:** acceso con sesión, cinco roles y bitácora · registro de internos ·
remisiones médicas · asignación de visitas · tarifario · cuentas y cobros · aviso
por correo al familiar.

**Pendiente:** catálogo de médicos, especialidades y exámenes · laboratorio y
farmacia · donaciones, gastos y cuota mensual · reportes.
