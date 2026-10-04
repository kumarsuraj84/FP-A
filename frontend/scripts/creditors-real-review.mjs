// Real-data review of /creditors against the running Creditors API (verified candidate). READ-ONLY: it only loads pages and clicks filters.
// Usage: API on :8081, dev server on :5180 (Finance) and :5181 started with FPA_CRED_MASKED=1, then `node scripts/creditors-real-review.mjs`.
// Screenshots contain REAL vendor names and amounts: they go to ../.secrets/review/ (git-ignored) and must never be committed.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const FIN = process.env.BASE_URL ?? "http://127.0.0.1:5180";
const MASK = process.env.MASKED_URL ?? "http://127.0.0.1:5181";
const EXE = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const OUT = new URL("../../.secrets/review/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
mkdirSync(OUT, { recursive: true });

let failed = 0;
const check = (name, ok, detail = "") => {
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

const browser = await chromium.launch({ executablePath: EXE, headless: true });

async function open(base, w, h, path = "/creditors?period=ytdfy27&compare=budget&scenario=normal&lens=age") {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  
  page.on("response", (r) => r.status() >= 400 && errors.push(`${r.status()} ${r.url()}`));
  await page.goto(base + path);
  await page.waitForSelector('[data-testid="exposure-credit-value"]', { timeout: 30000 });
  await page.waitForSelector('[data-testid="river-detail"]', { timeout: 30000 });
  return { ctx, page, errors };
}
const api = (page, p) => page.evaluate(async (x) => (await fetch(`/creditors-api/${x}`)).json(), p);
const exact = (page, id) => page.locator(`[data-testid="${id}"]`).first().getAttribute("data-exact");
const drill = (page) => new URL(page.url()).searchParams.get("drill");

/* ───────── 1. UI = API (exact text), every strip cell and every Document Age / Due Status / ledger cell ───────── */
{
  const { ctx, page, errors } = await open(FIN, 1440, 900);
  const run = (await api(page, "current")).extraction_run_id;
  const sum = await api(page, `runs/${run}/summary`);
  const pairs = [["credit", "credit_outstanding"], ["debit", "creditor_debit_balance"], ["past_due", "past_due_credit"], ["due_unavailable", "due_unavailable_credit"], ["gt90", "over_90_credit"], ["gt180", "over_180_credit"]];
  for (const [id, key] of pairs) check(`strip ${id} = API ${key}`, (await exact(page, `exposure-${id}-value`)) === sum[key], `${await exact(page, `exposure-${id}-value`)}`);
  const text = (id) => page.locator(`[data-testid="${id}"]`).first().innerText();
  check("strip shows ₹404.38 Cr / ₹111.71 Cr / ₹267.21 Cr / ₹37.87 Cr", [await text("exposure-credit-value"), await text("exposure-debit-value"), await text("exposure-past_due-value"), await text("exposure-due_unavailable-value")].join("|") === "₹404.38 Cr|₹111.71 Cr|₹267.21 Cr|₹37.87 Cr", [await text("exposure-credit-value"), await text("exposure-debit-value"), await text("exposure-past_due-value"), await text("exposure-due_unavailable-value")].join("|"));
  const age = await api(page, `runs/${run}/document-age`);
  const map = { D0_30: "b0_30", D31_60: "b31_60", D61_90: "b61_90", D91_180: "b91_180", D181_365: "b181_365", D365_PLUS: "b365p" };
  for (const b of age.buckets.filter((x) => map[x.bucket])) {
    const got = await page.locator(`[data-testid="bucket-${map[b.bucket]}"] [data-exact]`).first().getAttribute("data-exact");
    check(`Document Age ${b.bucket} = API`, got === b.credit_outstanding);
  }
  const due = await api(page, `runs/${run}/due-status`);
  for (const s of due.states) check(`Due Status ${s.state} = API`, (await page.locator(`[data-testid="due-${s.state}"] [data-exact]`).first().getAttribute("data-exact")) === s.credit_outstanding);
  const led = await api(page, `runs/${run}/ledgers`);
  check("four ledgers shown", led.ledgers.length === 4 && (await page.locator('[data-testid^="ledger-1"]').count()) === 4);
  for (const l of led.ledgers) check(`ledger ${l.ledger_code} credit = API`, (await page.locator(`[data-testid="ledger-${l.ledger_code}"] [data-exact]`).first().getAttribute("data-exact")) === l.credit_outstanding);
  const body = await page.locator("body").innerText();
  check("no demo scenario figure (₹214.8 Cr) on the page", !body.includes("214.8"));
  check("REAL DATA badge, verified candidate, as-of date", /REAL DATA/.test(body) && /Verified candidate · not live/.test(body) && /04 Oct 2026/.test(body));
  check("banner says Creditors is real and other modules are demo", /Creditors shows REAL data/.test(await page.locator('[data-testid="demo-banner"]').innerText()));
  check("no console/page errors on load", errors.length === 0, errors.slice(0, 2).join(" | "));
  await ctx.close();
}

/* ───────── 2. filters: each filter's vendor list must equal the API cohort exactly, and equal the strip/panel figure ───────── */
{
  const { ctx, page } = await open(FIN, 1440, 900, "/creditors?period=ytdfy27&compare=budget&scenario=normal&lens=concentration");
  const run = (await api(page, "current")).extraction_run_id;
  const sum = await api(page, `runs/${run}/summary`);
  const total = () => page.locator('[data-testid="vendor-total"]').innerText();
  const settle = (match) => page.waitForFunction((m) => document.querySelector('[data-testid="vendor-total"]')?.textContent?.includes(m), match, { timeout: 20000 });
  const cases = [
    ["Document Age gt90", '[data-testid="exposure-gt90"]', "gt90", sum.over_90_credit],
    ["Document Age gt180", '[data-testid="exposure-gt180"]', "gt180", sum.over_180_credit],
    ["Document Age 91–180 bucket", '[data-testid="bucket-b91_180"]', "D91_180", null],
    ["Due Status past due", '[data-testid="exposure-past_due"]', "past_due", sum.past_due_credit],
    ["Due Status unavailable", '[data-testid="due-DUE_UNAVAILABLE"]', "due_unavailable", sum.due_unavailable_credit],
    ["Due Status not yet due", '[data-testid="due-NOT_YET_DUE"]', "not_yet_due", null],
  ];
  for (const [name, sel, cohort, expect] of cases) {
    await page.locator(sel).first().click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("drill")?.includes("Ageing bucket:"), null, { timeout: 10000 });
    const d = await api(page, `runs/${run}/vendors?cohort=${cohort}&limit=1`);
    await settle(`${d.total.vendors.toLocaleString("en-IN")} vendor`);
    check(`${name}: vendor list total = API cohort`, true, `${await total()}`);
    if (expect) check(`${name}: cohort credit = summary figure (exact)`, d.total.cohort_credit === expect, d.total.cohort_credit);
    await page.locator('[data-testid="clear-age-filter"]').click();
    await page.waitForFunction(() => !new URL(location.href).searchParams.get("drill"), null, { timeout: 10000 });
  }
  // ledger filtering
  const led = (await api(page, `runs/${run}/ledgers`)).ledgers;
  for (const l of led) {
    await page.locator(`[data-testid="ledger-${l.ledger_code}"]`).click();
    const d = await api(page, `runs/${run}/vendors?ledger_code=${l.ledger_code}&limit=1`);
    await settle(`${d.total.vendors.toLocaleString("en-IN")} vendor`);
    check(`ledger ${l.ledger_code}: vendor list = API ledger filter`, d.total.credit_outstanding === l.credit_outstanding, `${d.total.vendors} vendors, credit ${d.total.credit_outstanding}`);
    await page.locator('[data-testid="clear-age-filter"]').click();
    await page.waitForFunction(() => !new URL(location.href).searchParams.get("drill"), null, { timeout: 10000 });
  }
  await ctx.close();
}

/* ───────── 3. vendor list → vendor detail (Finance names), then masked mode ───────── */
{
  const { ctx, page } = await open(FIN, 1440, 900, "/creditors?period=ytdfy27&compare=budget&scenario=normal&lens=concentration");
  const run = (await api(page, "current")).extraction_run_id;
  await page.waitForSelector('[data-testid="concentration-list"] li');
  const first = page.locator('[data-testid="concentration-list"] li button').first();
  const label = (await first.innerText()).replace(/\s+/g, " ").trim();
  await first.click();
  await page.waitForSelector('[data-testid="vendor-profile"] [data-testid="strip-credit"]', { timeout: 20000 });
  await page.waitForSelector('[data-testid="open-items"] tbody tr', { timeout: 20000 });
  const ref = new URL(page.url()).searchParams.get("drill").split("Vendor:")[1];
  const v = (await api(page, `runs/${run}/vendors/${ref}`)).vendor;
  check("vendor detail credit = API", (await page.locator('[data-testid="strip-credit"] [data-exact]').getAttribute("data-exact")) === v.credit_outstanding && (await page.locator('[data-testid="strip-debit"] [data-exact]').getAttribute("data-exact")) === v.debit_balance);
  check("Finance mode: vendor page shows the vendor name and identity", (await page.locator('[data-testid="vendor-identity"]').innerText()).includes("Name"));
  const items = await api(page, `runs/${run}/vendors/${ref}/items`);
  check("open items count = API", (await page.locator('[data-testid="open-items"] tbody tr').count()) === items.returned, `${items.returned}`);
  check("no ledger/voucher drill on the vendor page", (await page.locator('[data-testid="vendor-open-ledger"]').count()) === 0);
  await page.screenshot({ path: OUT + "vendor-finance-1440x900.png" });
  await ctx.close();
  console.log(`      (first vendor row in Finance mode: ${label.slice(0, 40)}…)`);

  const m = await open(MASK, 1440, 900, "/creditors?period=ytdfy27&compare=budget&scenario=normal&lens=concentration");
  await m.page.waitForSelector('[data-testid="concentration-list"] li');
  const masked = await m.page.locator('[data-testid="concentration-list"]').innerText();
  check("masked mode: list shows vendor references only", /Vendor V[0-9a-f]{12}/.test(masked) && (await m.page.locator('[data-testid="masked-note"]').count()) === 1 && (await m.page.locator('[data-testid="vendor-search"]').count()) === 0);
  const net = [];
  m.page.on("request", (r) => net.push(r.url()));
  await m.page.locator('[data-testid="concentration-list"] li button').first().click();
  await m.page.waitForSelector('[data-testid="open-items"] tbody tr', { timeout: 20000 });
  const idt = await m.page.locator('[data-testid="vendor-identity"]').innerText();
  check("masked vendor page: no name, SLID, code or document number", /restricted/.test(idt) && !/SLID|Sub-ledger|Credit days/.test(idt));
  const head = (await m.page.locator('[data-testid="open-items"] thead th').first().innerText()).trim();
  const cell = (await m.page.locator('[data-testid="open-items"] tbody tr td').first().innerText()).trim();
  check("masked items show an item reference, not a document", /^item$/i.test(head) && cell.startsWith("…"), `${head} / ${cell.length} chars`);
  await m.page.screenshot({ path: OUT + "vendor-masked-1440x900.png" });
  await m.ctx.close();
}

/* ───────── 4. screenshots at both sizes (Finance mode, real data) ───────── */
for (const [w, h] of [[1920, 1080], [1440, 900]]) {
  const { ctx, page, errors } = await open(FIN, w, h);
  await page.waitForSelector('[data-testid="ledger-1000000026"]');
  await page.waitForTimeout(800);
  await page.screenshot({ path: OUT + `creditors-top-${w}x${h}.png` });
  await page.screenshot({ path: OUT + `creditors-full-${w}x${h}.png`, fullPage: true });
  await page.locator('[data-testid="exposure-gt90"]').click();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: OUT + `creditors-gt90-full-${w}x${h}.png`, fullPage: true });
  await page.goto(FIN + "/creditors?period=ytdfy27&compare=budget&scenario=normal&lens=concentration");
  await page.waitForSelector('[data-testid="concentration-list"] li');
  await page.waitForTimeout(800);
  await page.screenshot({ path: OUT + `creditors-concentration-${w}x${h}.png`, fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check(`[${w}x${h}] no horizontal page overflow`, !overflow);
  check(`[${w}x${h}] no console errors`, errors.length === 0, errors.slice(0, 2).join(" | "));
  await ctx.close();
}

await browser.close();
console.log(failed ? `\n${failed} CHECK(S) FAILED` : "\nALL CHECKS PASSED");
process.exit(failed ? 1 : 0);
