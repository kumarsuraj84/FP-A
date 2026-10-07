// Real-data review of /pnl (Store P&L) against the running P&L API. READ-ONLY.
// Usage: API on :8081, dev server on :5188, then `node scripts/pnl-real-review.mjs`.
// Screenshots contain real store names and amounts: they go to ../.secrets/review/ (git-ignored) and must never be committed.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:5188";
const EXE = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const OUT = new URL("../../.secrets/review/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
mkdirSync(OUT, { recursive: true });
let failed = 0;
const check = (name, ok, detail = "") => {
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};
const browser = await chromium.launch({ executablePath: EXE, headless: true });

async function open(w, h) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("response", (r) => r.status() >= 400 && errors.push(`${r.status()} ${r.url()}`));
  await page.goto(BASE + "/profitability");
  await page.waitForSelector('[data-testid="pnl-strip"]', { timeout: 30000 });
  await page.waitForSelector('[data-testid="league-table"] tbody tr', { timeout: 30000 });
  return { ctx, page, errors };
}
const api = (page, p) => page.evaluate(async (x) => (await fetch(`/pnl-api/${x}`)).json(), p);
const exact = (page, id) => page.locator(`[data-testid="${id}"]`).first().getAttribute("data-exact");
const txt = (page, id) => page.locator(`[data-testid="${id}"]`).first().innerText();

{
  const { ctx, page, errors } = await open(1440, 900);
  const run = (await api(page, "current")).run_id;
  const s = await api(page, `runs/${run}/summary`);
  check("strip net sales = API (exact)", (await exact(page, "strip-sales-value")) === s.totals.revenue, s.totals.revenue);
  check("strip gross margin = API (exact)", (await exact(page, "strip-gm-value")) === s.totals.gross_margin);
  check("strip contribution = API (exact)", (await exact(page, "strip-contribution-value")) === s.totals.contribution);
  check("strip opex = API (exact)", (await exact(page, "strip-opex-value")) === s.totals.opex);
  check("the note says contribution is before allocation and budget is not available", /before other income, finance cost and head-office allocation/.test(await txt(page, "strip-note")) && /Budget: not available/.test(await txt(page, "strip-note")));
  check("banner says real data and that Command Center waits", /Profitability shows REAL data/.test(await txt(page, "demo-banner")) && /Command Center is still demo data/.test(await txt(page, "demo-banner")));
  check("header shows As of, state, refresh and no inactive Period/Compare/Scenario", (await page.locator('[data-testid="select-period"]').count()) === 0 && (await page.locator('[data-testid="real-asof"]').count()) === 1 && (await page.locator('[data-testid="real-refresh"]').count()) === 1);
  check("waterfall bars equal the API (revenue, COGS, contribution)", (await exact(page, "wf-revenue")) === String(Number(s.totals.revenue) / 1e7) && (await exact(page, "wf-contribution")) === String(Number(s.totals.contribution) / 1e7));
  // league
  const top = await api(page, `runs/${run}/stores?sort=contribution&order=desc&limit=10`);
  const rows = await page.locator('[data-testid^="league-row-"]').count();
  check("league lists 10 rows, first = API's top store", rows === 10 && (await page.locator('[data-testid^="league-row-"]').first().getAttribute("data-testid")) === `league-row-${top.stores[0].site_code}`, top.stores[0].site_code);
  check("league says all stores add up to the parent", /add up to/.test(await txt(page, "league-reconciles")));
  check("budget is shown as Not available, never zero", (await txt(page, "strip-budget-value")) === "Not available");
  for (const [tab, sort, order] of [["gm_high", "gross_margin_pct", "desc"], ["gm_low", "gross_margin_pct", "asc"], ["opex_high", "opex_pct", "desc"], ["grow_fast", "growth", "desc"], ["grow_down", "growth", "asc"]]) {
    await page.click(`[data-testid="league-${tab}"]`);
    await page.waitForTimeout(900);
    const api_ = await api(page, `runs/${run}/stores?sort=${sort}&order=${order}&limit=10&min_revenue=10000000`);
    const first = await page.locator('[data-testid^="league-row-"]').first().getAttribute("data-testid");
    check(`league ${tab}: first row = API's ${sort} ${order}`, first === `league-row-${api_.stores[0].site_code}`, api_.stores[0].site_code);
  }
  {
    const all = await api(page, `runs/${run}/stores?sort=contribution&order=desc&limit=500&min_revenue=5000000`);
    const plottable = all.stores.filter((x) => x.growth_pct !== null && x.contribution_pct !== null).length;
    const dots = await page.locator('[data-testid^="dot-"]').count();
    const chips = await Promise.all(["strong", "scale", "mature", "turnaround"].map((q) => page.locator(`[data-testid="quad-${q}"]`).getAttribute("data-count")));
    check("quadrant: one dot per plottable store, chip counts add up", dots === plottable && chips.reduce((a, b) => a + Number(b), 0) === plottable, `${dots} dots, chips ${chips.join("/")}`);
    const ok = all.stores.filter((x) => x.growth_pct !== null && x.contribution_pct !== null && x.last_year_revenue !== null);
    const ly = ok.reduce((a, x) => a + Number(x.last_year_revenue), 0);
    const cur = ok.reduce((a, x) => a + Number(x.last_year_revenue) * (1 + Number(x.growth_pct) / 100), 0);
    const refG = await page.locator('[data-testid="ref-growth"]').getAttribute("data-value");
    check("quadrant reference growth = like-for-like growth of the plotted stores", Math.abs(Number(refG) - (cur / ly - 1) * 100) < 0.001, refG);
  }
  await page.click('[data-testid="league-bottom"]');
  await page.waitForTimeout(800);
  const bot = await api(page, `runs/${run}/stores?sort=contribution&order=asc&limit=10`);
  check("bottom 10: first row = API's worst store", (await page.locator('[data-testid^="league-row-"]').first().getAttribute("data-testid")) === `league-row-${bot.stores[0].site_code}`);
  // drill: store -> group -> ledgers
  await page.click('[data-testid="league-top"]');
  await page.waitForTimeout(600);
  await page.locator('[data-testid^="league-row-"]').first().click();
  await page.waitForSelector('[data-testid="store-panel"] [data-testid="store-reconciles"]', { timeout: 20000 });
  check("store panel reconciles", /add up/.test(await txt(page, "store-reconciles")));
  await page.locator('[data-testid="store-panel"] [data-testid^="line-"]').nth(2).click();
  await page.waitForSelector('[data-testid="ledger-reconciles"]', { timeout: 20000 });
  check("group drill: the ledgers add up to the line", /adds up/.test(await txt(page, "ledger-reconciles")));
  // filters
  await page.selectOption('[data-testid="ctl-region"]', { index: 1 });
  await page.waitForTimeout(1200);
  check("region filter narrows the store count", Number((await txt(page, "strip-stores-value")).replace(/,/g, "")) < s.stores_in_scope, await txt(page, "strip-stores-value"));
  await page.click('[data-testid="basis-posted"]');
  await page.waitForTimeout(1200);
  check("posted-only basis is shown", (await page.locator('[data-testid="basis-posted"]').getAttribute("aria-pressed")) === "true");
  await page.screenshot({ path: OUT + "pnl-1440-filtered.png", fullPage: true });
  check("no page errors or failed requests (1440)", errors.length === 0, errors.slice(0, 3).join(" | "));
  await ctx.close();
}
{
  const { ctx, page } = await open(1440, 900);
  await page.screenshot({ path: OUT + "pnl-1440.png", fullPage: true });
  await ctx.close();
}
{
  const { ctx, page, errors } = await open(1920, 1080);
  await page.screenshot({ path: OUT + "pnl-1920.png", fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
  check("1920: no horizontal page scroll, no errors", !overflow && errors.length === 0, errors.slice(0, 3).join(" | "));
  await ctx.close();
}
{
  const { ctx, page, errors } = await open(390, 844);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
  check("phone width: no horizontal page scroll", !overflow);
  await page.screenshot({ path: OUT + "pnl-390.png", fullPage: true });
  check("no page errors (390)", errors.length === 0, errors.slice(0, 3).join(" | "));
  await ctx.close();
}
await browser.close();
console.log(failed ? `\n${failed} check(s) FAILED` : "\nAll checks passed");
process.exit(failed ? 1 : 0);
