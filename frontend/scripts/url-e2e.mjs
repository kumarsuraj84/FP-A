// Real-browser check of URL-addressable investigation state.
// Usage: dev server on :5180, then `node scripts/url-e2e.mjs`
import { chromium } from "playwright-core";

const BASE = process.env.BASE_URL ?? "http://localhost:5180";
const EXE = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const results = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
const page = await ctx.newPage();
const T = 8000;
const title = () => page.locator('[data-testid="drawer-title"]').textContent({ timeout: T });
const drill = () => new URL(page.url()).searchParams.get("drill");
const crumbs = () => page.locator('[data-testid="breadcrumbs"]').innerText().then((t) => t.replace(/\s*\n\s*/g, " / "));
const waitTitle = (t) => page.waitForFunction((x) => document.querySelector('[data-testid="drawer-title"]')?.textContent === x, t, { timeout: T });

await page.goto(`${BASE}/?period=ytdfy27&compare=budget&scenario=normal`);
await page.waitForSelector('[data-testid="bar-gm_impact"]');

// 1. drill: bar → Menswear → North → Rohini
await page.click('[data-testid="bar-gm_impact"]');
await page.click('[data-testid="drill-row-Department:Menswear"]');
await waitTitle("Menswear");
await page.click('[data-testid="split-tab-Region"]');
await page.click('[data-testid="drill-row-Region:North"]');
await waitTitle("North");
await page.click('[data-testid="split-tab-Store"]');
await page.click('[data-testid="drill-row-Store:Rohini"]');
await waitTitle("Rohini");
const deepLink = page.url();
check("URL carries the drill hierarchy", drill() === "hero:profit.gm_impact/Department:Menswear/Region:North/Store:Rohini", deepLink);

// 2. refresh restores the investigation
await page.reload();
await waitTitle("Rohini");
check("refresh restores the drawer on Rohini", (await title()) === "Rohini");
check("refresh restores breadcrumbs", (await crumbs()) === "CityKart / CFO Command Center / Gross Margin Impact / Menswear / North / Rohini", await crumbs());
check("refresh restores the amount", /₹/.test(await page.locator('[data-testid="drawer-amount"]').innerText()));

// 3. a brand new browser context (no storage) opens the copied link
const ctx2 = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
const p2 = await ctx2.newPage();
await p2.goto(deepLink);
await p2.waitForFunction(() => document.querySelector('[data-testid="drawer-title"]')?.textContent === "Rohini", null, { timeout: T });
check("a copied link opens the same investigation in a fresh browser", true);
await ctx2.close();

// 4. browser Back unwinds step by step, Forward replays
await page.goBack();
await waitTitle("North");
check("Back → North", drill().endsWith("Region:North"));
await page.goBack();
await waitTitle("Menswear");
check("Back → Menswear", drill().endsWith("Department:Menswear"));
await page.goBack();
await waitTitle("Gross Margin Impact");
check("Back → movement", drill() === "hero:profit.gm_impact");
await page.goForward();
await waitTitle("Menswear");
check("Forward → Menswear", drill().endsWith("Department:Menswear"));

// 5. breadcrumb Back keeps filters and updates the URL
await page.goto(deepLink);
await waitTitle("Rohini");
await page.click('[data-testid="crumb-3"]'); // Menswear
await waitTitle("Menswear");
check("breadcrumb → Menswear updates URL", drill() === "hero:profit.gm_impact/Department:Menswear");
await page.click('[data-testid="crumb-1"]'); // CFO Command Center
await page.waitForSelector('[data-testid="investigation-drawer"]', { state: "detached", timeout: T });
check("breadcrumb → Command Center clears drill, keeps filters", drill() === null && new URL(page.url()).searchParams.get("scenario") === "normal");

// 6. ledger + voucher pages are deep-linkable
await page.goto(deepLink);
await waitTitle("Rohini");
await page.click('[data-testid="open-ledger"]');
await page.waitForSelector('[data-testid="ledger-table"]');
await page.click('[data-testid="ledger-row-E3"]');
await page.waitForSelector('[data-testid="evidence"]');
const voucherUrl = page.url();
await page.reload();
await page.waitForSelector('[data-testid="evidence"]', { timeout: T });
check("refresh on the voucher page restores it", new URL(page.url()).pathname === "/voucher", voucherUrl);
await page.goBack();
await page.waitForSelector('[data-testid="ledger-table"]', { timeout: T });
check("Back from voucher → ledger", new URL(page.url()).pathname === "/ledger");
await page.goBack();
await page.waitForSelector('[data-testid="drawer-terminal"]', { timeout: T });
check("Back from ledger → drawer", new URL(page.url()).pathname === "/");

// 7. changing a filter keeps the drill and doesn't stack history
const lenBefore = await page.evaluate(() => history.length);
await page.selectOption('[data-testid="select-scenario"]', "margin_pressure");
await page.waitForFunction(() => new URL(location.href).searchParams.get("scenario") === "margin_pressure");
await waitTitle("Rohini");
check("scenario change keeps drill, replaces history entry", (await page.evaluate(() => history.length)) === lenBefore && drill() !== null);

// 8. stale/tampered link falls back safely
await page.goto(`${BASE}/?period=sep26&compare=ly&scenario=cash_pressure&drill=${encodeURIComponent("hero:profit.gm_impact/Department:Atlantis")}`);
await page.waitForSelector('[data-testid="bar-gm_impact"]');
await page.waitForFunction(() => !new URL(location.href).searchParams.get("drill"), null, { timeout: T });
check("tampered link falls back to the command center, filters kept", new URL(page.url()).searchParams.get("scenario") === "cash_pressure");

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
console.log(`Example deep link: ${deepLink}`);
process.exit(failed.length ? 1 : 0);
