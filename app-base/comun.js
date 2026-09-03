/* =====================================================================
   Codigo comun de las pantallas del Asilo «Cabeza de Algodon»
   =====================================================================

   Todas las pantallas hacen las mismas cuatro cosas: llamar al sistema,
   explicar en espanol lo que sale mal, revisar los formularios antes de
   enviarlos y mostrar arriba quien esta trabajando. Eso vive aqui.

   Cada pantalla lo incluye asi:

       <link rel="stylesheet" href="/comun.css">
       <script src="/comun.js"></script>

   ===================================================================== */


/* =====================================================================
   1. Llamadas al sistema
   =====================================================================

   Todas las direcciones son del MISMO origen y empiezan por /api/.
   La pantalla no conoce ninguna maquina ni ningun puerto: pide
   /api/tarifas y ya. La sesion viaja sola en la cookie.

   Los recursos disponibles son:

       /api/pacientes      fichas de los internos
       /api/solicitudes    remisiones del medico general
       /api/visitas        visitas medicas ya programadas
       /api/tarifas        tarifario del asilo
       /api/cargos         cargos a la cuenta del interno
       /api/estado-cuenta  cuenta completa de un interno
   ===================================================================== */

// Que se le dice a la persona cuando un modulo del sistema no responde.
// Se habla de MODULOS DEL ASILO, no de servicios ni de contenedores:
// quien lee esto es la secretaria, no quien programo el sistema.
// Se escriben sin articulo, porque van pegados a «El módulo de …».
const MODULO_DE = {
  "pacientes":     "registro de internos",
  "solicitudes":   "remisiones médicas",
  "visitas":       "visitas médicas",
  "tarifas":       "cobros",
  "cargos":        "cobros",
  "estado-cuenta": "cobros"
};

function mensajeNoDisponible(ruta) {
  const recurso = String(ruta).split("?")[0].split("/")[2] || "";
  const modulo = MODULO_DE[recurso];
  return modulo
    ? `El módulo de ${modulo} no está disponible en este momento. Avise al encargado del sistema.`
    : `Esa parte del sistema no está disponible en este momento. Avise al encargado del sistema.`;
}

/**
 * Hace una llamada al sistema y traduce la respuesta.
 *
 * Devuelve el cuerpo ya convertido, o null cuando no viene cuerpo.
 * Si algo sale mal lanza un Error con dos propiedades utiles:
 *
 *   .codigo   el codigo que respondio el sistema
 *   .detalle  el detalle crudo, SOLO cuando es un 422 de validacion,
 *             para que el formulario lo traduzca campo por campo
 */
async function api(ruta, opciones = {}) {
  let respuesta;

  try {
    respuesta = await fetch(ruta, {
      ...opciones,
      headers: { "Content-Type": "application/json", ...(opciones.headers || {}) }
    });
  } catch {
    // Ni siquiera se pudo salir del navegador: no hay red o la maquina
    // esta apagada. No es culpa de ningun modulo en particular.
    const error = new Error("No se pudo comunicar con el sistema. Revise su conexión e intente de nuevo.");
    error.codigo = 0;
    throw error;
  }

  // 401: la sesion vencio o nunca existio. No hay nada que explicar,
  // se devuelve a la persona a la pantalla de ingreso.
  if (respuesta.status === 401) {
    location.replace("/");
    const error = new Error("sin sesión");
    error.codigo = 401;
    throw error;
  }

  if (respuesta.status === 204) return null;

  const cuerpo = await respuesta.json().catch(() => ({}));

  if (respuesta.ok) return cuerpo;

  const error = new Error("");
  error.codigo = respuesta.status;

  if (respuesta.status === 403) {
    // El sistema explica cual rol y por que; a la persona le basta con
    // saber que no le corresponde hacerlo.
    error.message = "No tiene permiso para realizar esta acción.";

  } else if (respuesta.status === 503) {
    error.message = mensajeNoDisponible(ruta);

  } else if (respuesta.status === 422) {
    // El detalle se conserva TAL CUAL. Cada formulario sabe como se
    // llaman sus campos en espanol y lo traduce con sus etiquetas.
    error.message = "Hay datos que no se pudieron aceptar.";
    error.detalle = cuerpo.detail;

  } else {
    error.message = typeof cuerpo.detail === "string"
      ? cuerpo.detail
      : "No se pudo completar la operación.";
  }

  throw error;
}

/**
 * Version silenciosa, para los datos de adorno.
 *
 * Cuando la pantalla pide algo POR SU CUENTA -las cifras de las
 * tarjetas del panel, por ejemplo- y el rol no tiene permiso, eso NO es
 * un error que la persona deba ver: es lo normal. La secretaria no lee
 * los cargos y no tiene por que enterarse de que la pantalla lo intento.
 *
 * Devuelve el valor de reserva ante cualquier tropiezo. La unica
 * excepcion es el 401, que siempre manda al ingreso.
 *
 * En cambio, cuando la persona PULSA UN BOTON y le falta el permiso, se
 * usa api() normal y el 403 si se le avisa.
 */
async function apiSilenciosa(ruta, reserva = null) {
  try {
    return await api(ruta);
  } catch (error) {
    if (error.codigo === 401) throw error;
    return reserva;
  }
}


/* =====================================================================
   2. Encabezado
   ===================================================================== */

const porId = (id) => document.getElementById(id);

/** Dibuja la barra superior dentro del <header> de la pantalla. */
function montarEncabezado(subtitulo) {
  document.querySelector("header").innerHTML = `
    <div class="barra">
      <div>
        <h1>Asilo de Ancianos «Cabeza de Algodón»</h1>
        <div class="sub">${subtitulo}</div>
      </div>
      <div class="identidad">
        <div class="quien" id="yo-nombre">…</div>
        <div class="identidad-pie">
          <span class="rol mono" id="yo-rol">…</span>
          <a class="boton-barra" href="/panel">Panel</a>
          <button class="boton-barra" id="yo-salir">Salir</button>
        </div>
      </div>
    </div>`;

  porId("yo-salir").addEventListener("click", async () => {
    try { await fetch("/api/logout", { method: "POST" }); } catch {}
    location.replace("/");
  });
}

/**
 * Arranque comun de una pantalla: dibuja el encabezado, averigua quien
 * entro y comprueba que le corresponda esta pantalla.
 *
 * Devuelve los datos de la persona, o null si no le corresponde. Quien
 * llama debe parar cuando reciba null.
 */
async function iniciarPantalla({ subtitulo, requiere }) {
  montarEncabezado(subtitulo);

  let yo;
  try {
    yo = await api("/api/yo");
  } catch (error) {
    if (error.codigo !== 401) {
      document.querySelector("main").innerHTML =
        `<section class="tarjeta"><p class="vacio">${error.message}</p></section>`;
    }
    return null;
  }

  porId("yo-nombre").textContent = yo.nombre;
  porId("yo-rol").textContent = yo.rol_nombre;

  // El panel ya no le muestra esta pantalla a quien no le toca, pero
  // alguien puede llegar por un enlace guardado. Mejor decirlo claro
  // que dejarlo pelear con botones que siempre fallan.
  if (requiere && !yo.recursos.includes(requiere)) {
    document.querySelector("main").innerHTML = `
      <section class="tarjeta">
        <h2>Esta pantalla no le corresponde</h2>
        <p class="ayuda">Su puesto en el asilo no incluye esta tarea.
           Vuelva al panel para ver lo que sí le corresponde.</p>
        <div class="acciones"><a class="boton-barra"
             style="border-color:var(--pino);color:var(--pino);"
             href="/panel">Volver al panel</a></div>
      </section>`;
    return null;
  }

  return yo;
}


/* =====================================================================
   3. Errores de validacion en espanol
   =====================================================================

   Cuando el sistema rechaza los datos responde con un arreglo tecnico
   como este:

     [{"type":"string_too_short","loc":["body","paciente_id"],
       "msg":"String should have at least 1 character", ...}]

   Eso es lo que la persona veia en pantalla. Aqui se convierte en
   «Código del interno: debe tener al menos 1 carácter» y ademas se
   marca el campo culpable.

   Cada formulario se describe con cuatro cosas:

     ids          de que casilla sale cada dato
     ETIQUETAS    como se llama ese dato en espanol
     OBLIGATORIOS que no puede ir vacio
     MINIMOS      largo minimo que exige el sistema
   ===================================================================== */

// «1 caracteres» se lee mal, y varios campos tienen minimo 1.
const caracteres = (n) => (Number(n) === 1 ? "1 carácter" : `${n} caracteres`);

const MENSAJES_TECNICOS = {
  missing:            ()  => "hace falta llenarlo",
  string_too_short:   (d) => `debe tener al menos ${caracteres(d.ctx && d.ctx.min_length)}`,
  string_too_long:    (d) => `no puede pasar de ${caracteres(d.ctx && d.ctx.max_length)}`,
  greater_than:       (d) => `debe ser mayor que ${d.ctx && d.ctx.gt}`,
  greater_than_equal: (d) => `no puede ser menor que ${d.ctx && d.ctx.ge}`,
  less_than_equal:    (d) => `no puede pasar de ${d.ctx && d.ctx.le}`,
  int_parsing:        ()  => "debe ser un número entero",
  float_parsing:      ()  => "debe ser un número",
  // Un «value_error» trae el texto que escribio quien programo la regla,
  // y ese ya viene en espanol... salvo el del correo, que lo redacta la
  // libreria en ingles. Ese se cambia por uno del asilo.
  value_error:        (d) => {
    const bruto = (d.msg || "").replace(/^Value error,\s*/i, "");
    return /valid email address/i.test(bruto)
      ? "no parece un correo; escríbalo como hija@correo.com"
      : bruto;
  },
  literal_error:      (d) => `debe ser uno de estos valores: `
                             + String((d.ctx && d.ctx.expected) || "").replace(/'/g, "")
};

const inputDe = (form, campo) => porId(form.ids[campo]);

function limpiarErrores(form) {
  Object.keys(form.ids).forEach(campo => {
    const input = inputDe(form, campo);
    if (input) input.classList.remove("malo");
    const caja = porId("e-" + form.ids[campo]);
    if (caja) { caja.classList.remove("visible"); caja.textContent = ""; }
  });
  const aviso = porId(form.aviso);
  if (aviso) aviso.className = "aviso";
}

function marcarError(form, campo, mensaje) {
  const input = inputDe(form, campo);
  if (input) input.classList.add("malo");
  const caja = porId("e-" + form.ids[campo]);
  if (caja) { caja.textContent = mensaje; caja.classList.add("visible"); }
}

/** Aviso de una linea, o de una linea con la lista de lo que falta. */
function avisoResumen(form, titulo, faltantes, ok) {
  const caja = porId(form.aviso);
  if (!caja) return;
  caja.className = "aviso " + (ok ? "ok" : "error");
  caja.innerHTML = faltantes && faltantes.length
    ? `<strong>${titulo}</strong><ul>${faltantes.map(f => `<li>${f}</li>`).join("")}</ul>`
    : `<strong>${titulo}</strong>`;
}

/** Aviso suelto, para lo que no sale de un formulario. */
function avisar(idAviso, texto, ok = true) {
  const caja = porId(idAviso);
  if (!caja) return;
  caja.className = "aviso " + (ok ? "ok" : "error");
  caja.textContent = texto;
}

// Lleva la pantalla hasta el primer campo marcado DE ESTE formulario,
// para no saltar a un error viejo que quedo en otra tarjeta.
function irAlPrimerError(form) {
  const campo = Object.keys(form.ids)
    .map(c => inputDe(form, c))
    .find(el => el && el.classList.contains("malo"));
  if (!campo) return;
  // Varios formularios viven dentro de un plegable. Si esta cerrado hay
  // que abrirlo, o la persona no veria el campo marcado.
  const plegable = campo.closest("details");
  if (plegable) plegable.open = true;
  campo.scrollIntoView({ behavior: "smooth", block: "center" });
}

// Revisa en el navegador ANTES de enviar: el error sale de inmediato,
// sin gastar un viaje, y ya viene escrito en espanol.
function validarLocalmente(form) {
  const faltantes = [];

  (form.OBLIGATORIOS || []).forEach(campo => {
    const input = inputDe(form, campo);
    if (!input || !String(input.value).trim()) {
      marcarError(form, campo, "Este dato es obligatorio.");
      faltantes.push(form.ETIQUETAS[campo]);
    }
  });

  Object.keys(form.MINIMOS || {}).forEach(campo => {
    const input = inputDe(form, campo);
    const valor = input ? String(input.value).trim() : "";
    if (valor && valor.length < form.MINIMOS[campo]) {
      marcarError(form, campo, `Debe tener al menos ${caracteres(form.MINIMOS[campo])}.`);
      faltantes.push(`${form.ETIQUETAS[campo]} (muy corto)`);
    }
  });

  return faltantes;
}

/** Traduce el rechazo del sistema y marca el campo culpable. */
function traducirErrorDelServicio(form, detalle) {
  if (typeof detalle === "string") return [detalle];
  if (!Array.isArray(detalle)) return ["No se pudieron aceptar los datos."];

  return detalle.map(d => {
    const campo = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null;
    const nombre = form.ETIQUETAS[campo] || "Dato";
    const traductor = MENSAJES_TECNICOS[d.type];
    let msg = traductor ? traductor(d) : (d.msg || "valor no válido");
    msg = msg.replace(/^Value error,\s*/i, "");
    if (campo && form.ids[campo]) {
      marcarError(form, campo, msg.charAt(0).toUpperCase() + msg.slice(1) + ".");
    }
    return `${nombre}: ${msg}`;
  });
}

/**
 * Muestra lo que salio mal al enviar un formulario.
 *
 * Un rechazo de datos (422) trae el detalle campo por campo y se
 * despliega como lista. Cualquier otro tropiezo -sin permiso, modulo
 * caido- es una sola frase y ya viene lista desde api().
 */
function mostrarFallo(form, titulo, error) {
  if (error.codigo === 422 && error.detalle) {
    avisoResumen(form, titulo, traducirErrorDelServicio(form, error.detalle), false);
    irAlPrimerError(form);
  } else {
    avisoResumen(form, error.message, null, false);
  }
}


/* =====================================================================
   4. Ayudas de presentacion
   ===================================================================== */

/** Cantidades en quetzales, como se escriben en el recibo. */
const q = (n) => "Q " + Number(n || 0).toFixed(2);

/** Evita que un nombre con < o & desarme el HTML de una tabla. */
function texto(valor) {
  const caja = document.createElement("div");
  caja.textContent = valor == null ? "" : String(valor);
  return caja.innerHTML;
}

/** Fecha legible: «15 de septiembre de 2026, 09:30». */
function fechaLegible(valor) {
  if (!valor) return "";
  const fecha = new Date(String(valor).replace(" ", "T"));
  if (isNaN(fecha)) return String(valor);
  const dia = fecha.toLocaleDateString("es-GT", { day: "numeric", month: "long", year: "numeric" });
  const hora = fecha.toLocaleTimeString("es-GT", { hour: "2-digit", minute: "2-digit" });
  return `${dia}, ${hora}`;
}

/* Los estados se guardan en mayusculas y con la palabra del sistema
   («CONVERTIDA»). En pantalla se dice lo que significa para el asilo. */

const ESTADO_SOLICITUD = {
  PENDIENTE:  "Pendiente",
  CONVERTIDA: "Visita programada",
  ANULADA:    "Anulada"
};

const ESTADO_CARGO = {
  PENDIENTE: "Por cobrar",
  PAGADO:    "Pagado",
  ANULADO:   "Anulado"
};

/** Devuelve la etiqueta de color con el estado ya traducido. */
function insignia(estado, diccionario) {
  const clave = String(estado || "").toUpperCase();
  return `<span class="estado ${clave.toLowerCase()}">${diccionario[clave] || texto(clave)}</span>`;
}

/**
 * Llena un <select> con los internos registrados.
 *
 * Antes el codigo del interno se escribia a mano («PAC-001»), y quien
 * lo escribia tenia que acordarselo. Ahora se escoge de la lista.
 * Devuelve las fichas, para poder consultar despues el nombre del
 * interno o si le cubre la fundacion.
 */
async function llenarInternos(idSelect, { vacio = "— Seleccione al interno —" } = {}) {
  const selector = porId(idSelect);
  const internos = await apiSilenciosa("/api/pacientes", []);

  selector.innerHTML = `<option value="">${vacio}</option>` + internos.map(p =>
    `<option value="${texto(p.codigo)}">${texto(p.codigo)} · ${texto(p.nombres)} ${texto(p.apellidos)}</option>`
  ).join("");

  return internos;
}
