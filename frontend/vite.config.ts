// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - tanstackStart, viteReact, tailwindcss, tsConfigPaths, cloudflare (build-only),
//     componentTagger (dev-only), VITE_* env injection, @ path alias, React/TanStack dedupe,
//     error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... } }) if needed.
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

/**
 * DEV ONLY: `/creditors-api/*` is proxied to the read-only Creditors API. Finance routes (`/finance/`) get the Finance bearer token
 * added HERE, on the dev server, from the git-ignored `.secrets/cred_api.env` (or FPA_CRED_FINANCE_TOKEN). The token is never put in
 * the browser bundle and never logged. Set FPA_CRED_MASKED=1 to preview exactly what a non-Finance user would see (vendor_ref only).
 */
function financeToken(): string | undefined {
  if (process.env.FPA_CRED_MASKED === "1") return undefined;
  if (process.env.FPA_CRED_FINANCE_TOKEN) return process.env.FPA_CRED_FINANCE_TOKEN;
  const file = process.env.FPA_CRED_API_ENV ?? resolve(__dirname, "..", ".secrets", "cred_api.env");
  if (!existsSync(file)) return undefined;
  for (const line of readFileSync(file, "utf-8").split(/\r?\n/)) {
    const i = line.indexOf("=");
    if (i > 0 && line.slice(0, i).trim() === "finance_token") return line.slice(i + 1).trim() || undefined;
  }
  return undefined;
}

const target = process.env.FPA_CRED_API_PROXY ?? "http://127.0.0.1:8081";

export default defineConfig({
  vite: {
    server: {
      proxy: {
        "/creditors-api": {
          target,
          changeOrigin: false,
          rewrite: (path) => path.replace(/^\/creditors-api/, "/api/v1/creditors"),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq, req) => {
              proxyReq.removeHeader("authorization"); // never forward a browser-supplied credential
              const token = financeToken();
              if (token && (req.url ?? "").includes("/finance/")) proxyReq.setHeader("Authorization", `Bearer ${token}`);
            });
          },
        },
      },
    },
  },
});
