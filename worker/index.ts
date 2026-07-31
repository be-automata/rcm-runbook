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
      OS_SECURITY_KEY: env.OS_SECURITY_KEY,
      DATABASE_URL: env.DATABASE_URL,
      RCM_MODEL_ID: env.RCM_MODEL_ID,
      RCM_HOST: "0.0.0.0",
      RCM_PORT: "8080",
    };
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    return getContainer(env.RCM_CONTAINER, "rcm").fetch(request);
  },
};
