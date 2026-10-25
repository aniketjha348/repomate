/**
 * Runtime configuration. `NEXT_PUBLIC_` variables are inlined at build time,
 * so this reads identically on the server and in the browser.
 */
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
