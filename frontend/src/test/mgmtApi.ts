import { vi } from "vitest";
import { fixtureResponse } from "./mgmtFixture";

/** Serve the fixture through a stubbed fetch (tests only). `fail` makes every call fail with that status. */
export function installMgmtApi(opts: { fail?: number; pnl?: (u: URL) => unknown; months?: string[] } = {}) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      calls.push(url.pathname + url.search);
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
      if (!url.pathname.startsWith("/mgmt-api/")) return json({}, 404);
      if (opts.fail) return json({ detail: "boom" }, opts.fail);
      const path = url.pathname.slice("/mgmt-api/".length);
      const params = Object.fromEntries(url.searchParams.entries());
      if (path === "current" && opts.months) return json({ ...(fixtureResponse("current") as object), months: opts.months });
      if (path === "pnl" && opts.pnl) return json(opts.pnl(url));
      try {
        return json(fixtureResponse(path, params));
      } catch {
        return json({}, 404);
      }
    }),
  );
  return calls;
}
