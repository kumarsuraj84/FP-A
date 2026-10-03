// Real-browser check of the Creditors Control Room journey and URL state.
// Usage: dev server on :5180, then `node scripts/creditors-e2e.mjs`
import { chromium } from "playwright-core";

const BASE = process.env.BASE_URL ?? "http://localhost:5180";
const EXE = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const results = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const run = async (w, h) => {
  const tag = `${w}x${h}`;
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const page = await ctx.newPage();
  const T = 9000;
  const u = () => new URL(page.url());
  const drill = () => u().searchParams.get("drill");
  const hist = () => page.evaluate(() => history.length);
  const crumbs = () => page.locator('[data-testid="breadcrumbs"]').innerText().then((t) => t.replace(/\s*\n\s*/g, " / "));
  const waitDrill = (v) => page.waitForFunction((x) => new URL(location.href).searchParams.get("drill") === x, v, { timeout: T });
  const waitPath = (p) => page.waitForFunction((x) => location.pathname === x, p, { timeout: T });
  const c = (n, ok, d) => check(`[${tag}] ${n}`, ok, d);

  // 1. Command Center → Creditors hand-offs keep context
  await page.goto(`${BASE}/?period=q2fy27&compare=ly&scenario=aged_creditors`);
  await page.waitForSelector('[data-testid="pulse-creditors"]');
  await page.click('[data-testid="pulse-creditors"]');
  await waitPath("/creditors");
  await page.waitForSelector('[data-testid="river-b0_30"]');
  c("pulse → /creditors keeps period/compare/scenario", u().searchParams.get("period") === "q2fy27" && u().searchParams.get("compare") === "ly" && u().searchParams.get("scenario") === "aged_creditors" && drill() === null, page.url());
  await page.goBack();
  await page.waitForSelector('[data-testid="command-center"]');
  c("Back from room returns to the Command Center", u().pathname === "/");
  await page.click('[data-testid="risk-payables"]');
  await waitDrill("creditors.room/Ageing bucket:gt180");
  await page.waitForSelector('[data-testid="exposure-gt180"][aria-pressed="true"]');
  c("Payables risk → room prefiltered to >180 days", (await crumbs()).endsWith("Creditors / >180 days"), await crumbs());
  await page.goBack();
  await page.waitForSelector('[data-testid="command-center"]');
  await page.click('[data-testid="action-cta-creditors_181"]');
  await waitDrill("creditors.room/Ageing bucket:gt180");
  c("CFO focus '>180 days' → room prefiltered", true);

  // 2. river click + strip + lens: filters replace history
  await page.goto(`${BASE}/creditors?period=ytdfy27&compare=budget&scenario=normal&lens=age`);
  await page.waitForSelector('[data-testid="river-b0_30"]');
  const h0 = await hist();
  await page.click('[data-testid="river-b181_365"]');
  await waitDrill("creditors.room/Ageing bucket:b181_365");
  c("river click selects the bucket and updates the URL", (await page.getAttribute('[data-testid="bucket-b181_365"]', "aria-pressed")) === "true");
  await page.click('[data-testid="exposure-gt90"]');
  await waitDrill("creditors.room/Ageing bucket:gt90");
  await page.click('[data-testid="lens-movement"]');
  await page.waitForFunction(() => new URL(location.href).searchParams.get("lens") === "movement");
  c("age filter and lens changes do not add history entries", (await hist()) === h0, `${h0} → ${await hist()}`);
  await page.click('[data-testid="exposure-all"]');
  await page.waitForFunction(() => !new URL(location.href).searchParams.get("drill"));

  // 3. migration flow → drawer, refresh restores, Back closes
  await page.click('[data-testid="flow-b61_90>b91_180"]');
  await page.waitForSelector('[data-testid="investigation-drawer"] [data-testid="drawer-amount"]');
  c("migration flow opens the vendors drawer", (await page.locator('[data-testid="drawer-title"]').textContent()) === "61–90 → 91–180");
  await page.reload();
  await page.waitForSelector('[data-testid="investigation-drawer"] [data-testid="drawer-amount"]', { timeout: T });
  c("refresh restores the flow drawer", drill() === "creditors.room/Migration:b61_90>b91_180");
  await page.goBack();
  await page.waitForSelector('[data-testid="investigation-drawer"]', { state: "detached", timeout: T });
  c("browser Back closes the drawer", drill() === null || !drill().includes("Migration"));
  await page.goForward();
  await page.waitForSelector('[data-testid="investigation-drawer"] [data-testid="drawer-amount"]', { timeout: T });

  // 4. vendor → ledger → voucher, refresh, Back, breadcrumbs
  await page.locator('[data-testid="investigation-drawer"] [data-testid="drill-rows"] button').first().click();
  await waitPath("/creditors/vendor");
  await page.waitForSelector('[data-testid="vendor-profile"] [data-testid="lifecycle"]');
  const vendorUrl = page.url();
  c("drawer vendor row opens the vendor profile", /Vendor:V\d+/.test(drill()), await crumbs());
  await page.reload();
  await page.waitForSelector('[data-testid="vendor-profile"] [data-testid="lifecycle"]', { timeout: T });
  c("refresh restores the vendor profile", page.url() === vendorUrl);
  await page.click('[data-testid="vendor-open-ledger"]');
  await page.waitForSelector('[data-testid="ledger-table"]');
  await page.click('[data-testid="ledger-row-E2"]');
  await page.waitForSelector('[data-testid="evidence"]');
  const voucherCrumbs = await crumbs();
  c("breadcrumb keeps every stage to the voucher", /Creditors \/ 61–90 → 91–180 \/ .+ \/ GL \/ (PI|PV|DN)-26-\d+$/.test(voucherCrumbs), voucherCrumbs);
  await page.reload();
  await page.waitForSelector('[data-testid="evidence"]', { timeout: T });
  c("refresh restores the voucher page", u().pathname === "/voucher");
  await page.goBack();
  await page.waitForSelector('[data-testid="ledger-table"]', { timeout: T });
  await page.goBack();
  await page.waitForSelector('[data-testid="vendor-profile"]', { timeout: T });
  await page.goBack();
  await page.waitForSelector('[data-testid="creditors-room"]', { timeout: T });
  c("browser Back: voucher → ledger → vendor → room", u().pathname === "/creditors");

  // 5. breadcrumb Back from a vendor reached through a filter
  await page.goto(`${BASE}/creditors/vendor?period=ytdfy27&compare=budget&scenario=aged_creditors&lens=abnormal&drill=${encodeURIComponent("creditors.room/Ageing bucket:gt180/Vendor:V10011")}`);
  await page.waitForSelector('[data-testid="crumb-3"]', { timeout: T });
  await page.click('[data-testid="crumb-3"]');
  await waitPath("/creditors");
  c("breadcrumb → '>180 days' keeps scenario, lens and filter", u().searchParams.get("scenario") === "aged_creditors" && u().searchParams.get("lens") === "abnormal" && drill() === "creditors.room/Ageing bucket:gt180");
  await page.click('[data-testid="crumb-2"]');
  await page.waitForFunction(() => !new URL(location.href).searchParams.get("drill"));
  c("breadcrumb → 'Creditors' clears the filter only", u().pathname === "/creditors" && u().searchParams.get("scenario") === "aged_creditors");

  // 6. abnormal path: Creditors → Abnormal → Debit balance → vendor
  await page.goto(`${BASE}/creditors?period=ytdfy27&compare=budget&scenario=vendor_advance_risk&lens=abnormal`);
  await page.click('[data-testid="abnormal-debit_balance"]');
  await page.waitForSelector('[data-testid="investigation-drawer"] [data-testid="drawer-amount"]');
  await page.locator('[data-testid="investigation-drawer"] [data-testid="drill-rows"] button').first().click();
  await waitPath("/creditors/vendor");
  c("Creditors → Abnormal → Debit balance → vendor", (await crumbs()).includes("Debit balance in creditor account"), await crumbs());

  // 7. data states
  for (const [state, sel] of [["unavailable", '[data-testid="state-unavailable"]'], ["error", '[data-testid="state-error"]'], ["stale", '[data-testid="stale-chip"]']]) {
    await page.goto(`${BASE}/creditors?period=ytdfy27&compare=budget&scenario=normal&lens=age&data=${state}`);
    await page.waitForSelector(sel, { timeout: T });
    const text = await page.locator('[data-testid="creditors-room"]').innerText();
    c(`${state} state is shown, with no fake zeros`, !/₹0\.00 Cr/.test(text));
  }
  await ctx.close();
};

await run(1920, 1080);
await run(1440, 900);
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
console.log(`Example creditor deep link: ${BASE}/creditors/vendor?period=ytdfy27&compare=budget&scenario=normal&lens=age&drill=${encodeURIComponent("creditors.room/Ageing bucket:gt180/Vendor:V10003")}`);
process.exit(failed.length ? 1 : 0);
