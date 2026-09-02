-- =====================================================================
-- Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"
-- Universidad Mariano Galvez de Guatemala - Centro Regional de Mazatenango
-- Analisis y Diseno de Sistemas II
--
-- Este script se ejecuta UNA SOLA VEZ, cuando el contenedor de MySQL
-- arranca con el volumen de datos vacio. La imagen oficial de MySQL
-- corre automaticamente todo archivo .sql que encuentre en la carpeta
-- /docker-entrypoint-initdb.d
--
-- Aqui NO se crean tablas. Solo se crea el "terreno" de cada
-- microservicio: su esquema y su usuario. Las tablas las crea cada
-- servicio al arrancar, desde su propio db.py, igual que hoy.
-- =====================================================================

-- utf8mb4 es el juego de caracteres que guarda bien tildes y enies.
-- Sin esto, "Muñoz" o "Sagastume Villavicencio" se guardan corruptos.
SET NAMES utf8mb4;


-- ---------------------------------------------------------------------
-- 1. Un esquema (base de datos) por microservicio
--
-- Este es el patron "database per service" del documento de
-- arquitectura: ningun servicio ve las tablas de otro. La diferencia
-- con la version anterior es que en vez de 6 archivos .db sueltos,
-- ahora son 6 esquemas dentro de un mismo motor MySQL.
--
-- ms-reportes no aparece aqui a proposito: no tiene base de datos.
-- Arma los informes preguntandole por HTTP a los demas servicios.
-- ---------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS asilo_gateway
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS asilo_pacientes
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS asilo_catalogo
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS asilo_solicitudes
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS asilo_clinico
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS asilo_cobros
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;


-- ---------------------------------------------------------------------
-- 2. Un usuario por microservicio, con permiso SOLO sobre su esquema
--
-- Esto es lo que vuelve real el aislamiento. Si manana ms-cobros
-- intentara leer la tabla de pacientes, MySQL se lo niega aunque el
-- programador se equivoque: no tiene permiso, no es solo una regla
-- escrita en un documento.
--
-- El '%' significa "desde cualquier host de la red de Docker".
-- ---------------------------------------------------------------------

CREATE USER IF NOT EXISTS 'u_gateway'@'%'     IDENTIFIED BY 'gateway_2026';
CREATE USER IF NOT EXISTS 'u_pacientes'@'%'   IDENTIFIED BY 'pacientes_2026';
CREATE USER IF NOT EXISTS 'u_catalogo'@'%'    IDENTIFIED BY 'catalogo_2026';
CREATE USER IF NOT EXISTS 'u_solicitudes'@'%' IDENTIFIED BY 'solicitudes_2026';
CREATE USER IF NOT EXISTS 'u_clinico'@'%'     IDENTIFIED BY 'clinico_2026';
CREATE USER IF NOT EXISTS 'u_cobros'@'%'      IDENTIFIED BY 'cobros_2026';

GRANT ALL PRIVILEGES ON asilo_gateway.*     TO 'u_gateway'@'%';
GRANT ALL PRIVILEGES ON asilo_pacientes.*   TO 'u_pacientes'@'%';
GRANT ALL PRIVILEGES ON asilo_catalogo.*    TO 'u_catalogo'@'%';
GRANT ALL PRIVILEGES ON asilo_solicitudes.* TO 'u_solicitudes'@'%';
GRANT ALL PRIVILEGES ON asilo_clinico.*     TO 'u_clinico'@'%';
GRANT ALL PRIVILEGES ON asilo_cobros.*      TO 'u_cobros'@'%';

FLUSH PRIVILEGES;
