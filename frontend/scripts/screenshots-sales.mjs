// Visual and navigation QA for the Home and Sales Comparison sample prototype.
// Usage: dev server running, then `BASE_URL=http://127.0.0.1:5181 node scripts/screenshots-sales.mjs`
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:5181";
const EXE = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const OUT = process.env.OUT_DIR ?? "D:/AI_WORKING/FPA/docs/sales/prototype-screens";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
const report = { consoleErrors: [], checks: {} };
page.on("console", (m) => m.type() === "error" && !/404|favicon/.test(m.text()) && report.consoleErrors.push(m.text().slice(0, 200)));
page.on("pageerror", (e) => report.consoleErrors.push(String(e).slice(0, 200)));
const settle = () => page.waitForTimeout(700);
const shot = (name, full = false) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
const has = (id) => page.locator(`[data-testid="${id}"]`).count().then((n) => n > 0);

// direct access and refresh: Home
await page.goto(`${BASE}/home`, { waitUntil: "networkidle" });
await settle();
report.checks.home_direct = { title: await page.title(), landing: await has("landing"), overflow: await overflow() };
await page.reload({ waitUntil: "networkidle" });
await settle();
report.checks.home_refresh = { title: await page.title(), landing: await has("landing") };
await shot("01-landing");

// direct access and refresh: Sales Comparison
await page.goto(`${BASE}/operations/sales`, { waitUntil: "networkidle" });
await settle();
report.checks.sales_direct = { title: await page.title(), page: await has("sales-comparison"), banner: await has("sample-banner"), overflow: await overflow() };
await page.reload({ waitUntil: "networkidle" });
await settle();
report.checks.sales_refresh = { title: await page.title(), page: await has("sales-comparison"), kpis: await has("kpi-strip") };
await shot("02-sales-overview");
await shot("02b-sales-overview-full", true);

// detail state: a store with missing days, under All stores
await page.click('[data-testid="cohort-all"]');
await page.click('[data-testid="open-S13"]');
await page.waitForSelector('[data-testid="store-detail"]');
await settle();
report.checks.detail = { banner: await has("detail-sample-banner"), coverage: await page.textContent('[data-testid="detail-coverage"]') };
await shot("03-store-detail");
await page.keyboard.press("Escape");

// unequal custom period
await page.click('[data-testid="mode-custom"]');
await settle();
report.checks.custom = { perStoreDay: await page.textContent('[data-testid="kpi-sales-note"]'), note: await page.textContent('[data-testid="plan-note"]') };
await page.locator('[data-testid="controls"]').screenshot({ path: `${OUT}/04-custom-period-controls.png` });
await shot("04-custom-period", false);

// reference with no data
await page.fill('[data-testid="ref-start"]', "2020-01-01");
await page.fill('[data-testid="ref-end"]', "2020-01-04");
await settle();
report.checks.no_reference = { text: await page.textContent('[data-testid="no-reference"]'), growth: await page.textContent('[data-testid="kpi-sales-growth"]') };
await shot("05-no-reference");

// loading and empty states
await page.selectOption('[data-testid="sample-state"]', "loading");
await settle();
report.checks.loading = await has("loading");
await shot("06-loading");
await page.selectOption('[data-testid="sample-state"]', "empty");
await settle();
report.checks.empty = await has("empty");
await shot("07-empty");

// navigation: Sales -> Home -> Finance -> Home link -> Home
await page.goto(`${BASE}/operations/sales`, { waitUntil: "networkidle" });
await page.click('[data-testid="portal-nav-home"]');
await page.waitForSelector('[data-testid="landing"]');
await page.click('[data-testid="portal-nav-finance"]');
await page.waitForSelector('[data-testid="link-home"]');
report.checks.finance_has_home_link = true;
await shot("08-finance-with-home-link");
await page.click('[data-testid="link-home"]');
await page.waitForSelector('[data-testid="landing"]');
await page.click('[data-testid="tile-sales"]');
await page.waitForSelector('[data-testid="sales-comparison"]');
report.checks.navigation_round_trip = true;

// / is still the CFO Command Center
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await settle();
report.checks.root = { title: await page.title(), financeShell: await has("demo-banner") };

writeFileSync(`${OUT}/qa-report.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
await browser.close();
