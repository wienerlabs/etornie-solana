// Live demo: run with `npx tsx examples/demo.ts`
// Env: ETORNIE_API_URL, ETORNIE_TEST_EMAIL, ETORNIE_TEST_PASSWORD
import { EtornieClient, EtornieApiError } from "../src/index.js";

const baseUrl = process.env.ETORNIE_API_URL!;
const email = process.env.ETORNIE_TEST_EMAIL!;
const password = process.env.ETORNIE_TEST_PASSWORD!;

const etornie = new EtornieClient({ baseUrl });

const tokens = await etornie.auth.login(email, password);
console.log("login ok, token len:", tokens.access_token.length);

const me = await etornie.auth.me();
console.log("me:", me.email, "| role:", me.role, "| id:", me.id.slice(0, 8) + "…");

const { cases, total } = await etornie.cases.list({ limit: 5 });
console.log("cases.list -> total:", total, "| returned:", cases.length);

const exportBytes = await etornie.dataExport.download("json");
console.log("dataExport(json) -> bytes:", exportBytes.byteLength);

try {
  await etornie.cases.get("00000000-0000-0000-0000-000000000000");
} catch (err) {
  if (err instanceof EtornieApiError) {
    console.log("error handling ok -> EtornieApiError status:", err.status);
  }
}

console.log("TS SDK DEMO OK");
