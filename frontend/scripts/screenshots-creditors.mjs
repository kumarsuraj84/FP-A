// Stage 2 visual QA: Creditors Control Room at 1920x1080 and 1440x900, with layout checks.
// Usage: dev server on :5180, then `node scripts/screenshots-creditors.mjs`
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = process.env.BASE_URL ?? "http://localhost:5180";
const EXE = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const OUT = new URL("../docs/screenshots/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
mkdirSync(OUT, { recursive: true });
const sizes = [
  { w: 1920, h: 1080 },
  { w: 1440, h: 900 },
];
const report = {};
const browser = await chromium.launch({ executablePath: EXE, headless: true });

for (const { w, h } of sizes) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const tag = `${w}x${h}`;
  const checks = { consoleErrors: [], horizontalOverflow: 0, clipped: [] };
  page.on("console", (m) => m.type() === "error" && !/404/.test(m.text()) && checks.consoleErrors.push(m.text().slice(0, 200)));
  page.on("pageerror", (e) => checks.consoleErrors.push(String(e).slice(0, 200)));
  const settle = () => page.waitForTimeout(900);
  const measure = async () => {
    checks.horizontalOverflow = Math.max(checks.horizontalOverflow, await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth));
    checks.clipped.push(
      ...(await page.evaluate(() => {
        const bad = [];
        for (const el of document.querySelectorAll("main *, aside *, header *, nav *")) {
          const cs = getComputedStyle(el);
          if (!el.childElementCount && el.textContent?.trim() && el.scrollWidth > el.clientWidth + 1 && cs.textOverflow !== "ellipsis" && cs.overflow !== "auto" && !el.closest("svg")) {
            bad.push(`${el.tagName.toLowerCase()}[${el.getAttribute("data-testid") ?? ""}] "${el.textContent.trim().slice(0, 40)}" ${el.scrollWidth}>${el.clientWidth}`);
          }
        }
        return bad.slice(0, 10);
      })),
    );
  };
  const shotEl = async (name, testId) => {
    const el = page.locator(`[data-testid="${testId}"]`);
    await el.scrollIntoViewIfNeeded();
    await el.screenshot({ path: `${OUT}s2-${name}-${tag}.png` });
  };
  const shot = async (name, full = false) => {
    await page.screenshot({ path: `${OUT}s2-${name}-${tag}.png`, fullPage: full });
  };

  // Command Center → Creditors hand-off carries context
  await page.goto(`${BASE}/?period=ytdfy27&compare=budget&scenario=aged_creditors`);
  await page.waitForSelector('[data-testid="risk-payables"]');
  await settle();
  await page.click('[data-testid="risk-payables"]'); // prefilters >180
  await page.waitForSelector('[data-testid="river-b0_30"]');
  await settle();
  await shot("01-handoff-from-risk-filtered");
  await measure();

  // fresh Normal room
  await page.goto(`${BASE}/creditors?period=ytdfy27&compare=budget&scenario=normal&lens=age`);
  await page.waitForSelector('[data-testid="river-b0_30"]');
  await settle();
  await shot("02-room");
  await shot("02-room-full", true);
  await measure();

  // river click → filter
  await page.click('[data-testid="river-b181_365"]');
  await settle();
  await shot("03-river-bucket-selected");
  await measure();

  // migration flow → drawer with vendors
  await page.click('[data-testid="flow-b61_90>b91_180"]');
  await page.waitForSelector('[data-testid="investigation-drawer"] [data-testid="drawer-amount"]');
  await page.mouse.move(3, 3);
  await settle();
  await shot("04-migration-flow-drawer");
  await measure();

  // lenses
  await page.click('[data-testid="drawer-close"]');
  await shotEl("05a-lens-age", "lens-workspace");
  await page.click('[data-testid="lens-concentration"]');
  await settle();
  await shotEl("05-lens-concentration", "lens-workspace");
  await page.click('[data-testid="lens-movement"]');
  await settle();
  await shotEl("06-lens-movement", "lens-workspace");
  await page.click('[data-testid="lens-abnormal"]');
  await settle();
  await shotEl("07-lens-abnormal", "lens-workspace");
  await measure();

  // vendor profile → ledger → voucher
  await page.click('[data-testid="lens-concentration"]');
  await page.click('[data-testid^="vendor-V"] >> nth=0');
  await page.waitForSelector('[data-testid="vendor-profile"] [data-testid="lifecycle"]');
  await settle();
  await shot("08-vendor-profile");
  await shot("08-vendor-profile-full", true);
  await measure();
  await page.click('[data-testid="vendor-open-ledger"]');
  await page.waitForSelector('[data-testid="ledger-table"]');
  await settle();
  await shot("09-vendor-ledger");
  await page.click('[data-testid="ledger-row-E2"]');
  await page.waitForSelector('[data-testid="evidence"]');
  await settle();
  await shot("10-voucher-evidence");
  await measure();

  // abnormal path: Creditors → Abnormal → debit balance → vendor
  await page.goto(`${BASE}/creditors?period=ytdfy27&compare=budget&scenario=vendor_advance_risk&lens=abnormal`);
  await page.waitForSelector('[data-testid="abnormal-debit_balance"]');
  await page.click('[data-testid="abnormal-debit_balance"]');
  await page.waitForSelector('[data-testid="investigation-drawer"] [data-testid="drawer-amount"]');
  await settle();
  await shot("11-abnormal-debit-balance-drawer");
  await measure();

  // Aged Creditors scenario
  await page.goto(`${BASE}/creditors?period=ytdfy27&compare=budget&scenario=aged_creditors&lens=concentration`);
  await page.waitForSelector('[data-testid="river-b0_30"]');
  await settle();
  await shot("12-aged-creditors-scenario-full", true);
  await measure();

  // data states
  for (const st of ["unavailable", "stale", "error"]) {
    await page.goto(`${BASE}/creditors?period=ytdfy27&compare=budget&scenario=normal&lens=age&data=${st}`);
    await page.waitForTimeout(1300);
    await shot(`13-state-${st}`);
  }

  report[tag] = checks;
  await ctx.close();
}
await browser.close();
writeFileSync(`${OUT}layout-report-creditors.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
