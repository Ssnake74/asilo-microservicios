-- =====================================================================
-- Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"
-- Universidad Mariano Galvez de Guatemala - Centro Regional de Mazatenango
-- Analisis y Diseno de Sistemas II
--
-- Se ejecuta una sola vez, cuando MySQL arranca con el volumen vacio.
-- Crea el esquema y el usuario de cada servicio; las tablas las crea
-- cada servicio al arrancar, desde su db.py.
-- =====================================================================

-- Sin utf8mb4, las tildes y las enies se guardan corruptas.
SET NAMES utf8mb4;


-- ---------------------------------------------------------------------
-- 1. Un esquema por microservicio ("database per service"): ningun
-- servicio ve las tablas de otro.
--
-- ms-reportes no tiene esquema: arma los informes pidiendole los datos
-- por HTTP a los demas servicios.
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
-- 2. Un usuario por microservicio, con permiso solo sobre su esquema
--
-- El aislamiento lo impone MySQL y no el codigo: si ms-cobros intenta
-- leer las tablas de pacientes, el motor se lo niega.
--
-- '%' = desde cualquier host de la red de Docker.
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
