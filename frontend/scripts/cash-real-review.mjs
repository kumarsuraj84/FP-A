// Real-data review of /cash (Liquidity & Working Capital Control) against the running Cash API. READ-ONLY.
// Usage: API on :8081, dev server on :5180, then `node scripts/cash-real-review.mjs`.
// Screenshots contain real store names and amounts: they go to ../.secrets/review/ (git-ignored) and must never be committed.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:5180";
const EXE = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const OUT = new URL("../../.secrets/review/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
mkdirSync(OUT, { recursive: true });
let failed = 0;
const check = (name, ok, detail = "") => {
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};
const browser = await chromium.launch({ executablePath: EXE, headless: true });
const URL_ = "/cash?period=ytdfy27&compare=budget&scenario=normal";

async function open(w, h) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("response", (r) => r.status() >= 400 && errors.push(`${r.status()} ${r.url()}`));
  await page.goto(BASE + URL_);
  await page.waitForSelector('[data-testid="bank-card"]', { timeout: 30000 });
  await page.waitForSelector('[data-testid="till-table"] tbody tr', { timeout: 30000 });
  return { ctx, page, errors };
}
const api = (page, p) => page.evaluate(async (x) => (await fetch(`/cash-api/${x}`)).json(), p);
const apiCred = (page, p) => page.evaluate(async (x) => (await fetch(`/creditors-api/${x}`)).json(), p);
const exact = (page, id) => page.locator(`[data-testid="${id}"]`).first().getAttribute("data-exact");
const txt = (page, id) => page.locator(`[data-testid="${id}"]`).first().innerText();

{
  const { ctx, page, errors } = await open(1440, 900);
  const run = (await api(page, "current")).run_id;
  const s = await api(page, `runs/${run}/summary`);
  check("strip Store Till Cash = API (exact)", (await exact(page, "strip-till-value")) === s.till.store_till_cash, s.till.store_till_cash);
  const cred = await apiCred(page, `runs/${s.creditors.creditors_run_id}/summary`);
  check("strip Credit Outstanding = Creditors API (exact)", (await exact(page, "strip-credit-value")) === cred.credit_outstanding, cred.credit_outstanding);
  check("strip Past Due Creditors = Creditors API (exact)", (await exact(page, "strip-pastdue-value")) === cred.past_due_credit);
  check("strip Creditor Debit Balances = Creditors API (exact)", (await exact(page, "strip-debit-value")) === cred.creditor_debit_balance);
  check("strip shows ₹1.49 Cr / ₹404.38 Cr / ₹267.21 Cr / ₹111.71 Cr", [await txt(page, "strip-till-value"), await txt(page, "strip-credit-value"), await txt(page, "strip-pastdue-value"), await txt(page, "strip-debit-value")].join("|") === "₹1.49 Cr|₹404.38 Cr|₹267.21 Cr|₹111.71 Cr", [await txt(page, "strip-till-value"), await txt(page, "strip-credit-value"), await txt(page, "strip-pastdue-value"), await txt(page, "strip-debit-value")].join("|"));
  const t = s.bank_review.totals;
  check("bank opening / posted / unposted / including = API", (await exact(page, "bank-opening-value")) === t.opening_balance && (await exact(page, "bank-posted-value")) === t.posted_closing && (await exact(page, "bank-unposted-value")) === t.unposted_movement && (await exact(page, "bank-indicative-value")) === t.including_unposted);
  check("bank shows −₹79.84 Cr posted and −₹5.07 Cr including unposted", (await txt(page, "bank-posted-value")) === "−₹79.84 Cr" && (await txt(page, "bank-indicative-value")) === "−₹5.07 Cr", `${await txt(page, "bank-posted-value")} | ${await txt(page, "bank-indicative-value")}`);
  check("status label PROVISIONAL · NOT BANK-RECONCILED", (await txt(page, "bank-status")) === "PROVISIONAL · NOT BANK-RECONCILED");
  check("driver is AXIS BANK-8218", (await txt(page, "bank-driver")).includes("AXIS BANK-8218"));
  const ledgers = (await api(page, `runs/${run}/bank-ledgers`)).ledgers.filter((l) => l.has_movement);
  check("bank table rows = ledgers with movement", (await page.locator('[data-testid="bank-table"] tbody tr').count()) === ledgers.length, `${ledgers.length}`);
  for (const l of ledgers) check(`ledger ${l.ledger_code} posted closing = API`, (await page.locator(`[data-testid="bank-ledger-${l.ledger_code}"] [data-exact]`).first().getAttribute("data-exact")) === l.posted_closing);
  const top = (await api(page, `runs/${run}/store-till?limit=15`)).stores;
  const firstExact = await page.locator('[data-testid="till-table"] tbody tr td[data-exact]').first().getAttribute("data-exact");
  check("till table: highest store = API", firstExact === top[0].cumulative_balance, top[0].cumulative_balance);
  check("till table: 15 rows then more", (await page.locator('[data-testid="till-table"] tbody tr').count()) === 15);
  const body = await page.locator("body").innerText();
  check("no cash position / forecast / horizon wording", !/Cash today|Cash in (7|15|30)|Cash Available|Operating minimum|above minimum|projected cash/i.test(body));
  check("no demo cash figure on the page", !/214\.8/.test(body));
  check("REAL DATA badge, verified candidate, as-of 04 Oct 2026", /REAL DATA/.test(body) && /Verified candidate · not live/.test(body) && /04 Oct 2026/.test(body));
  check("banner: Liquidity real, Command Center and Profitability demo", /Liquidity shows REAL data/.test(await page.locator('[data-testid="demo-banner"]').innerText()));
  check("bank card is outside the verified strip", (await page.locator('[data-testid="cash-strip"] [data-testid="bank-card"]').count()) === 0);
  for (const id of ["bank_reconciled_cash", "consolidated_cash", "cash_forecast", "inventory", "receivables", "vendor_advances", "payroll", "statutory", "capex"]) check(`unavailable ${id} shows a dash, no ₹`, !(await txt(page, `unavailable-${id}`)).includes("₹"));
  check("no console/page errors on load", errors.length === 0, errors.slice(0, 2).join(" | "));
  await page.locator('[data-testid="till-more"]').click();
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="till-table"] tbody tr').length === 65, null, { timeout: 15000 });
  check("Show more pages in 50 stores", true);
  await page.locator('[data-testid="open-creditors"]').click();
  await page.waitForSelector('[data-testid="creditors-room"]');
  check("Open Creditors Control lands on /creditors", new URL(page.url()).pathname === "/creditors");
  await ctx.close();
}

for (const [w, h] of [[1920, 1080], [1440, 900]]) {
  const { ctx, page, errors } = await open(w, h);
  await page.waitForTimeout(800);
  await page.screenshot({ path: OUT + `cash-top-${w}x${h}.png` });
  await page.screenshot({ path: OUT + `cash-full-${w}x${h}.png`, fullPage: true });
  check(`[${w}x${h}] no horizontal page overflow`, !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
  check(`[${w}x${h}] no console errors`, errors.length === 0, errors.slice(0, 2).join(" | "));
  await ctx.close();
}
await browser.close();
console.log(failed ? `\n${failed} CHECK(S) FAILED` : "\nALL CHECKS PASSED");
process.exit(failed ? 1 : 0);
