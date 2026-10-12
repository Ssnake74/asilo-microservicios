// Las cuatro aplicaciones del asilo en Azure Container Apps y el trabajo que
// crea los esquemas y usuarios de MySQL. El entorno, la red, el registro y el
// servidor MySQL ya existen: se crean una sola vez desde Cloud Shell.
// Se despliega con desplegar.sh, que esta en esta misma carpeta.

@description('Etiqueta de las imagenes en el registro: el commit que las construyo.')
param etiqueta string

@secure()
@description('Clave del administrador de MySQL (asiloadmin).')
param claveAdmin string

@secure()
@description('Contrasena de aplicacion de la cuenta de Gmail que envia los avisos.')
param claveCorreo string

param usuarioCorreo string = 'ssnakillar74@gmail.com'

@description('Replicas minimas por aplicacion. 0 = escala a cero sin trafico.')
param minimoReplicas int = 0

param ubicacion string = resourceGroup().location

var esquemas = ['gateway', 'pacientes', 'catalogo', 'solicitudes', 'clinico', 'cobros']
var certificados = '/etc/ssl/certs/ca-certificates.crt'

// La clave de cada usuario de servicio sale de la del administrador: es la
// misma en cada despliegue y no hay que guardarla en ningun lado.
func claveDe(admin string, esquema string) string => 'Sv${uniqueString(admin, esquema)}X9'

var sqlEsquemas = join(map(esquemas, e =>
  'CREATE DATABASE IF NOT EXISTS asilo_${e} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER IF NOT EXISTS \'u_${e}\'@\'%\' IDENTIFIED BY \'${claveDe(claveAdmin, e)}\'; ALTER USER \'u_${e}\'@\'%\' IDENTIFIED BY \'${claveDe(claveAdmin, e)}\'; GRANT ALL PRIVILEGES ON asilo_${e}.* TO \'u_${e}\'@\'%\';'), ' ')

resource entorno 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: 'cae-asilo'
}

resource registro 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: 'asiloae0794'
}

resource mysql 'Microsoft.DBforMySQL/flexibleServers@2023-12-30' existing = {
  name: 'asilo-mysql-ae0794'
}

var servidorMysql = mysql.properties.fullyQualifiedDomainName
var credencialesRegistro = registro.listCredentials()

// ---------------------------------------------------------------------
// Trabajo de un solo uso: crea los seis esquemas y sus usuarios. Corre
// dentro de la red privada, el unico lugar desde donde se llega a MySQL.
// ---------------------------------------------------------------------
resource trabajoEsquemas 'Microsoft.App/jobs@2024-03-01' = {
  name: 'job-esquemas'
  location: ubicacion
  properties: {
    environmentId: entorno.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 300
      replicaRetryLimit: 1
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: [
        { name: 'clave-admin', value: claveAdmin }
        { name: 'sql', value: sqlEsquemas }
      ]
    }
    template: {
      containers: [
        {
          name: 'mysql'
          image: 'mysql:8.0'
          command: ['sh', '-c']
          args: ['mysql -h "$DB_HOST" -u asiloadmin --ssl-mode=REQUIRED -e "$SQL" && echo ESQUEMAS LISTOS']
          env: [
            { name: 'DB_HOST', value: servidorMysql }
            { name: 'MYSQL_PWD', secretRef: 'clave-admin' }
            { name: 'SQL', secretRef: 'sql' }
          ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
    }
  }
}

// ---------------------------------------------------------------------
// Aplicaciones. Solo el gateway tiene ingress externo (RNF-03); los
// microservicios se alcanzan por su nombre dentro del entorno.
// ---------------------------------------------------------------------
var servicios = [
  {
    nombre: 'asilo-cabeza'
    imagen: 'gateway'
    esquema: 'gateway'
    puerto: 8080
    externo: true
    extra: [
      { name: 'MS_PACIENTES_URL', value: 'http://ms-pacientes' }
      { name: 'MS_SOLICITUDES_URL', value: 'http://ms-solicitudes' }
      { name: 'MS_COBROS_URL', value: 'http://ms-cobros' }
      { name: 'COOKIE_SEGURA', value: '1' }
    ]
  }
  {
    nombre: 'ms-pacientes'
    imagen: 'ms-pacientes'
    esquema: 'pacientes'
    puerto: 8083
    externo: false
    extra: []
  }
  {
    nombre: 'ms-solicitudes'
    imagen: 'ms-solicitudes'
    esquema: 'solicitudes'
    puerto: 8081
    externo: false
    extra: [
      { name: 'MS_COBROS_URL', value: 'http://ms-cobros' }
      { name: 'SMTP_HOST', value: 'smtp.gmail.com' }
      { name: 'SMTP_PORT', value: '587' }
      { name: 'SMTP_USUARIO', value: usuarioCorreo }
      { name: 'SMTP_CLAVE', secretRef: 'clave-correo' }
      { name: 'SMTP_REMITENTE', value: 'Asilo Cabeza de Algodón <${usuarioCorreo}>' }
    ]
  }
  {
    nombre: 'ms-cobros'
    imagen: 'ms-cobros'
    esquema: 'cobros'
    puerto: 8082
    externo: false
    extra: []
  }
]

resource aplicaciones 'Microsoft.App/containerApps@2024-03-01' = [for s in servicios: {
  name: s.nombre
  location: ubicacion
  properties: {
    environmentId: entorno.id
    configuration: {
      ingress: {
        external: s.externo
        targetPort: s.puerto
        transport: 'auto'
        // Dentro del entorno el gateway llama por HTTP; afuera, solo HTTPS.
        allowInsecure: !s.externo
      }
      registries: [
        {
          server: registro.properties.loginServer
          username: credencialesRegistro.username
          passwordSecretRef: 'clave-registro'
        }
      ]
      secrets: concat([
        { name: 'clave-registro', value: credencialesRegistro.passwords[0].value }
        { name: 'clave-bd', value: claveDe(claveAdmin, s.esquema) }
      ], s.nombre == 'ms-solicitudes' ? [{ name: 'clave-correo', value: claveCorreo }] : [])
    }
    template: {
      containers: [
        {
          name: s.imagen
          image: '${registro.properties.loginServer}/asilo/${s.imagen}:${etiqueta}'
          env: concat([
            { name: 'TZ', value: 'America/Guatemala' }
            { name: 'DB_HOST', value: servidorMysql }
            { name: 'DB_PORT', value: '3306' }
            { name: 'DB_USER', value: 'u_${s.esquema}' }
            { name: 'DB_PASSWORD', secretRef: 'clave-bd' }
            { name: 'DB_NAME', value: 'asilo_${s.esquema}' }
            { name: 'DB_SSL_CA', value: certificados }
          ], s.extra)
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: {
        minReplicas: minimoReplicas
        maxReplicas: 1
      }
    }
  }
}]

output url string = 'https://${aplicaciones[0].properties.configuration.ingress.fqdn}'
