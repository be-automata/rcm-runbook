/**
 * Worker que enruta el tráfico al contenedor con el Facilitador RCM.
 *
 * El contenedor corre la app FastAPI tal cual (Python + agno), así que no hay
 * dos implementaciones que mantener sincronizadas. El Worker solo decide a qué
 * instancia va cada petición y le entrega los secretos.
 *
 * Todas las sesiones van a una única instancia (`"rcm"`): el estado del análisis
 * vive en Postgres, pero mantener una sola instancia evita arranques en frío
 * innecesarios mientras el cliente conversa.
 */
import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  RCM_CONTAINER: DurableObjectNamespace<RcmContainer>;
  ANTHROPIC_API_KEY: string;
  OS_SECURITY_KEY: string;
  DATABASE_URL: string;
  RCM_MODEL_ID: string;
}

export class RcmContainer extends Container<Env> {
  defaultPort = 8080;
  // El facilitador tarda ~6 s por turno y el cliente escribe pausado entre
  // preguntas: dormir antes de 20 min lo obligaría a esperar un arranque en
  // frío en mitad de la entrevista.
  sleepAfter = "20m";
  // /health no exige llave, así que sirve para saber si ya está listo.
  pingEndpoint = "/health";
  // Sale a api.anthropic.com y a Neon.
  enableInternet = true;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    // Los secretos del Worker no llegan solos al contenedor: hay que pasarlos
    // como variables de entorno del proceso.
    this.envVars = {
      ANTHROPIC_API_KEY: env.ANTHROPIC_API_KEY,
      // Con el nombre `RCM_` a propósito, no `OS_SECURITY_KEY`: ese nombre lo
      // lee también el `AgnoAPISettings()` por defecto de agno, lo que activaba
      // su propia dependencia de auth — que solo acepta `Authorization: Bearer`
      // y rechazaba `?key=`. Producción se comportaba distinto que local y los
      // enlaces clicables dejaban de funcionar en las rutas de agno.
      // Nuestra config acepta ambos nombres (AliasChoices en config.py).
      RCM_OS_SECURITY_KEY: env.OS_SECURITY_KEY,
      DATABASE_URL: env.DATABASE_URL,
      RCM_MODEL_ID: env.RCM_MODEL_ID,
      RCM_HOST: "0.0.0.0",
      RCM_PORT: "8080",
    };
  }
}

/**
 * Página de espera, en español y con recarga sola.
 *
 * Sin esto, cuando el contenedor está arrancando el cliente ve el error crudo
 * del proxy de Cloudflare: «Error proxying request to container: The container
 * is not running». En medio de una demo, eso es una página en blanco con un
 * mensaje en inglés que nadie sabe interpretar.
 */
function paginaDespertando(): Response {
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Facilitador RCM — iniciando</title>
<meta http-equiv="refresh" content="5">
<style>body{margin:0;height:100dvh;display:flex;align-items:center;justify-content:center;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f6f7f9;color:#1a1a1a}
.c{max-width:420px;padding:28px;text-align:center}h1{font-size:18px;margin:0 0 10px;color:#1F4E78}
p{margin:.4em 0;color:#555;line-height:1.5}small{color:#999}</style></head>
<body><div class="c"><h1>Iniciando el Facilitador RCM</h1>
<p>El sistema estaba en reposo y está arrancando. Tarda unos segundos.</p>
<p>Esta página se recarga sola; no hace falta que haga nada.</p>
<small>Si sigue viendo esto pasado un minuto, avise a quien le compartió el enlace.</small>
</div></body></html>`;
  return new Response(html, {
    status: 503,
    headers: { "content-type": "text/html; charset=utf-8", "retry-after": "5" },
  });
}

/**
 * ¿Esta respuesta es «el contenedor no está listo» disfrazado de 500?
 *
 * `@cloudflare/containers` NO lanza cuando el contenedor está arrancando:
 * captura el fallo y devuelve `new Response(..., { status: 500 })` con el texto
 * en inglés (ver `dist/lib/container.js`, «Error proxying request to container»
 * y «Container suddenly disconnected»). Un `try/catch` alrededor del fetch
 * nunca se dispara — eso fue justo el error de la primera versión de este
 * arreglo, que parecía correcta y era código muerto.
 */
const AVISOS_DE_LA_LIBRERIA = [
  "Error proxying request to container", // container.js:975
  "Container suddenly disconnected", // :972
  "Failed to start container", // :879 — la del arranque en frío
  "There is no Container instance available", // :874, llega como 503
  "Origin is disallowed", // :204 y siguientes, llega como 520
];

async function estaArrancando(res: Response): Promise<boolean> {
  // No basta con mirar el 500: la librería devuelve además 503, 429 y 520, todos
  // con texto en inglés. La primera versión de esto solo cubría dos de las cinco
  // cadenas y el 500 del arranque en frío se seguía escapando al cliente.
  if (res.status < 429) return false;
  // El 429 va por estado, sin exigir cadena: container.js:876 devuelve el
  // mensaje crudo del rate-limit («you are requesting too many containers per
  // second»), que no tiene prefijo fijo y por eso escapaba a la lista. Y un 429
  // desde el contenedor es, por definición, «todavía no puedo atenderte».
  if (res.status === 429) return true;
  const texto = await res.clone().text().catch(() => "");
  return AVISOS_DE_LA_LIBRERIA.some((aviso) => texto.includes(aviso));
}

function respuestaDeEspera(request: Request): Response {
  // Al navegador, una página en español; a la API, JSON.
  const quiereHtml = (request.headers.get("accept") || "").includes("text/html");
  return quiereHtml
    ? paginaDespertando()
    : new Response(
        JSON.stringify({ detail: "El sistema está iniciando. Reintente en unos segundos." }),
        { status: 503, headers: { "content-type": "application/json", "retry-after": "5" } },
      );
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const contenedor = getContainer(env.RCM_CONTAINER, "rcm");
    // Solo se reintenta lo idempotente. Un POST a /runs que llegó y se cortó
    // después duplicaría el turno del cliente y le cobraría dos veces el modelo.
    // Aun así, al POST también se le cambia el 500 en inglés por el aviso.
    const reintentable = request.method === "GET" || request.method === "HEAD";
    const intentos = reintentable ? 3 : 1;
    for (let i = 0; i < intentos; i++) {
      let res: Response;
      try {
        res = await contenedor.fetch(request);
      } catch (e) {
        console.warn("contenedor lanzó", String(e));
        if (i === intentos - 1) return respuestaDeEspera(request);
        await new Promise((r) => setTimeout(r, 1500));
        continue;
      }
      if (!(await estaArrancando(res))) return res;
      console.warn("contenedor arrancando, intento", i + 1);
      if (i === intentos - 1) return respuestaDeEspera(request);
      await new Promise((r) => setTimeout(r, 1500));
    }
    return respuestaDeEspera(request);
  },
};
