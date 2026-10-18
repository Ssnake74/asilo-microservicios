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
                              ├──► ms-solicitudes ──┬──► ms-cobros
                              │                     └──► ms-catalogo
                              ├──► ms-cobros
                              ├──► ms-catalogo ──► ms-cobros (precios)
                              └──► ms-clinico ──► ms-solicitudes, ms-catalogo, ms-cobros

MySQL 8: un esquema y un usuario por servicio
```

| Servicio | Responsabilidad |
|---|---|
| `gateway` | Sirve las pantallas, abre la sesión, decide qué puede hacer cada rol, reenvía la petición al servicio que corresponde y lleva la bitácora. |
| `ms-pacientes` | Registro de los internos y de su familiar responsable. |
| `ms-solicitudes` | Remisiones del médico general y su conversión en visita médica. Avisa por correo al familiar. |
| `ms-cobros` | Tarifario, cargos con el descuento de la fundación y estado de cuenta. También las entradas y salidas del asilo: cuotas mensuales, donaciones, gastos y la cuenta con la fundación. |
| `ms-catalogo` | Especialidades, médicos, enfermeros, exámenes y medicamentos de la fundación. |
| `ms-clinico` | Ficha médica de la visita, exámenes y sus resultados, recetas y su despacho, e historial del interno. Cobra lo que el laboratorio hizo y la farmacia entregó. |

- El gateway es la única entrada: los microservicios no publican puerto (RNF-03).
- Cada servicio entra a MySQL con su propio usuario y solo ve su esquema. Lo impone
  el motor, no el código (RNF-04).
- Si `ms-cobros` no responde, la visita, el resultado o el despacho se registran
  igual y quedan pendientes de cobro (RNF-12). Cuando cobros vuelve, el cargo se
  genera solo (RNF-13).
- La remisión y la visita eligen especialidad, médico y enfermero del catálogo, y la
  regla RN-05 compara identificadores. Sin el catálogo no se puede comprobar esa
  regla, así que una remisión o visita que lo usa espera a que responda.

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

### Variables de producción

En desarrollo no hace falta definirlas: el compose ya trae las suyas. En Azure se
declaran en cada Container App, y las claves como secretos (RNF-21).

| Variable | Servicio | Qué hace |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Todos | Conexión a MySQL |
| `DB_SSL_CA` | Todos | Certificado raíz con que se verifica a MySQL; activa TLS. En las imágenes: `/etc/ssl/certs/ca-certificates.crt` |
| `COOKIE_SEGURA` | `gateway` | Con `1`, la cookie de sesión solo viaja por HTTPS |
| `MS_PACIENTES_URL`, `MS_SOLICITUDES_URL`, `MS_COBROS_URL`, `MS_CATALOGO_URL`, `MS_CLINICO_URL` | `gateway` | Dirección de cada microservicio |
| `MS_COBROS_URL`, `MS_CATALOGO_URL` | `ms-solicitudes` | Dirección de cobros y del catálogo |
| `MS_COBROS_URL` | `ms-catalogo` | Dirección de cobros, para dar precio a los exámenes y medicamentos sembrados |
| `MS_SOLICITUDES_URL`, `MS_CATALOGO_URL`, `MS_COBROS_URL` | `ms-clinico` | Visita que se atiende, examen o medicamento del catálogo, y cobro de lo hecho |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_REMITENTE` | `ms-solicitudes` | Servidor de correo y remitente |
| `SMTP_USUARIO`, `SMTP_CLAVE` | `ms-solicitudes` | Activan STARTTLS y el inicio de sesión en el servidor de correo |
| `REINTENTO_SEGUNDOS` | `ms-solicitudes`, `ms-clinico` | Cada cuánto se reintentan los cargos pendientes; por omisión 15 |

### Publicación de imágenes

Cada push a `main` construye las imágenes de los seis servicios y las publica en el registro de
Azure, etiquetadas con el commit (`.github/workflows/publicar-imagenes.yml`). Los
cambios que solo tocan documentación o pruebas no disparan la construcción. Las
credenciales del registro son los secretos `ACR_USUARIO` y `ACR_CLAVE` del
repositorio.

### Despliegue en Azure

Las seis aplicaciones y el trabajo que crea los esquemas de MySQL están
descritos en `infra/azure/asilo.bicep`. Se despliegan desde Cloud Shell con un
solo comando, que usa las imágenes más recientes del registro:

```bash
bash asilo-microservicios/infra/azure/desplegar.sh
```

Pide la clave del administrador de MySQL y la contraseña de aplicación del correo.
La clave de cada usuario de servicio se deriva de la del administrador, así que
no hay que guardarla aparte.

---

## 3. Usuarios de demostración

| Usuario | Rol | Qué hace |
|---|---|---|
| `admin` | Administrador | Todo, administra los usuarios y consulta la bitácora |
| `secretaria` | Secretaria del asilo | Registra a los internos y a sus familiares |
| `medico` | Médico general | Remite al interno a una especialidad |
| `fundacion` | Fundación | Asigna horario, médico y enfermero, convierte la remisión en visita y mantiene el catálogo médico |
| `caja` | Caja y cobros | Tarifario, cobros y estado de cuenta |
| `especialista` | Médico especialista | Atiende la visita y completa la ficha médica |
| `laboratorio` | Laboratorio clínico | Registra los resultados de los exámenes |
| `farmacia` | Farmacia | Despacha los medicamentos recetados |

Contraseña de todos en desarrollo: `asilo2026`. Cinco intentos fallidos en quince
minutos bloquean al usuario.

Cada persona del asilo tiene su propia cuenta. El administrador la crea en
«Usuarios del sistema» con una contraseña temporal; al entrar por primera vez,
la persona tiene que elegir la suya. El administrador también restablece la
contraseña a quien la olvida, cambia el puesto y desactiva a quien deja el
asilo. Las cuentas no se borran, para que la bitácora siga diciendo quién hizo
cada cosa.

---

## 4. Estructura

```
app-base/        Pantallas: HTML, CSS y JavaScript sin framework. Las sirve el gateway
gateway/         app/  main.py · seguridad.py · db.py · schemas.py
ms-pacientes/    app/  main.py · reglas.py · db.py · schemas.py
ms-solicitudes/  app/  los mismos, más cliente_cobros.py, cliente_catalogo.py y notificaciones.py
ms-cobros/       app/  main.py · reglas.py · db.py · schemas.py
ms-catalogo/     app/  main.py · reglas.py · db.py · schemas.py
ms-clinico/      app/  los mismos, más clientes.py
infra/mysql/init/01-esquemas.sql   Esquemas y usuarios de MySQL
infra/azure/     Plantilla y script del despliegue en Azure
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
| `/api/usuarios`, `/api/usuarios/roles`, `/api/usuarios/{id}/restablecer` | gateway: cuentas de usuario, solo para el administrador |
| `/api/mi-contrasena` | gateway: cambio de la contraseña propia |
| `/api/pacientes` | `ms-pacientes` |
| `/api/solicitudes`, `/api/visitas` | `ms-solicitudes` |
| `/api/tarifas`, `/api/cargos`, `/api/estado-cuenta` | `ms-cobros` |
| `/api/cuotas`, `/api/donaciones`, `/api/gastos`, `/api/fundacion/deuda`, `/api/fundacion/pagos` | `ms-cobros` |
| `/api/catalogo/especialidades`, `/medicos`, `/enfermeros`, `/examenes`, `/medicamentos` | `ms-catalogo` |
| `/api/fichas`, `/api/examenes`, `/api/resultados`, `/api/recetas`, `/api/despachos` | `ms-clinico` |

Qué rol puede usar cada ruta está en la tabla `PERMISOS` de
`gateway/app/seguridad.py`. Lo que no aparece ahí se niega.

---

## 6. Pruebas

Con el sistema levantado, desde la raíz del repositorio:

```powershell
powershell -ExecutionPolicy Bypass -File .\pruebas\ejecutar.ps1
```

Son 218 casos en 18 grupos, cada uno ligado al requisito que verifica. El reporte
queda en `pruebas/resultado.txt` y lista los casos que fallan y los pendientes
conocidos.

---

## 7. Estado

**Construido:** acceso con sesión, roles y bitácora · registro de internos ·
remisiones médicas · asignación de visitas con médico y enfermero · catálogo
médico · tarifario · cuentas y cobros · aviso por correo al familiar ·
administración de usuarios con contraseña temporal · ficha médica, laboratorio,
farmacia e historial médico con su cobro.

**Construido también:** cuotas mensuales, donaciones, gastos y cuenta con la
fundación · egreso o fallecimiento del interno conservando su historial ·
reintento automático de los cargos pendientes.

**Pendiente:** reportes.
