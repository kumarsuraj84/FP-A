// Product review gate: the eight screens at 1920x1080 and 1440x900, plus two end-to-end journeys
// (filmstrip PNGs and a screen recording each). Usage: dev server on :5180, then `node scripts/screenshots-stage34.mjs`
import { chromium } from "playwright-core";
import { mkdirSync, renameSync, writeFileSync } from "node:fs";

const BASE = process.env.BASE_URL ?? "http://localhost:5180";
const EXE = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const root = new URL("../docs/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const OUT = `${root}review/`;
const DEMO = `${root}review/journeys/`;
mkdirSync(OUT, { recursive: true });
mkdirSync(DEMO, { recursive: true });
const Q = "period=ytdfy27&compare=budget&scenario=normal";
const sizes = [
  { w: 1920, h: 1080 },
  { w: 1440, h: 900 },
];
const report = {};
const browser = await chromium.launch({ executablePath: EXE, headless: true });

function tracker(page, checks) {
  page.on("console", (m) => m.type() === "error" && !/404|favicon/.test(m.text()) && checks.consoleErrors.push(m.text().slice(0, 200)));
  page.on("pageerror", (e) => checks.consoleErrors.push(String(e).slice(0, 200)));
  return async () => {
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
}

/** Walks Profitability → store → driver → GL → ledger → voucher. Returns once on the voucher page. */
async function profitDrill(page, shot) {
  await page.click('[data-testid="dot-rohini"]');
  await page.waitForSelector('[data-testid="bar-gm_var"]');
  await page.waitForTimeout(700);
  await shot("store");
  await page.click('[data-testid="bar-gm_var"]');
  await page.waitForSelector('[data-testid="investigation-drawer"] [data-testid="drill-rows"]');
  await page.mouse.move(3, 3);
  await page.waitForTimeout(500);
  await shot("movement-drawer");
  await page.click('[data-testid="investigation-drawer"] [data-testid^="drill-row-Department:"] >> nth=0');
  await page.waitForTimeout(500);
  await shot("driver-department");
  await page.click('[data-testid="split-tab-Account"]');
  await page.click('[data-testid="investigation-drawer"] [data-testid^="drill-row-Account:"] >> nth=0');
  await page.waitForSelector('[data-testid="drawer-terminal"]');
  await page.waitForTimeout(400);
  await shot("gl-account");
  await page.click('[data-testid="open-ledger"]');
  await page.waitForSelector('[data-testid="ledger-table"]');
  await page.waitForTimeout(500);
  await shot("ledger");
  await page.click('[data-testid="ledger-row-E2"]');
  await page.waitForSelector('[data-testid="evidence"]');
  await page.waitForTimeout(500);
  await shot("voucher");
}

for (const { w, h } of sizes) {
  const tag = `${w}x${h}`;
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const checks = { consoleErrors: [], horizontalOverflow: 0, clipped: [] };
  const measure = tracker(page, checks);
  const settle = (ms = 900) => page.waitForTimeout(ms);
  const shot = async (name, full = false) => page.screenshot({ path: `${OUT}${name}-${tag}.png`, fullPage: full });

  // 1 Command Center
  await page.goto(`${BASE}/?${Q}`);
  await page.waitForSelector('[data-testid="pulse-cash"]');
  await settle(1200);
  await shot("01-command-center");
  await measure();

  // 2 Creditors Control
  await page.goto(`${BASE}/creditors?${Q}&lens=age`);
  await page.waitForSelector('[data-testid="river-b0_30"]');
  await settle();
  await shot("02-creditors-control");
  await measure();

  // 3 Profitability portfolio (+ a quadrant filter)
  await page.goto(`${BASE}/profitability?${Q}`);
  await page.waitForSelector('[data-testid="dot-rohini"]');
  await settle();
  await shot("03-profitability-portfolio");
  await shot("03-profitability-portfolio-full", true);
  await measure();
  await page.click('[data-testid="quadrant-turnaround"]');
  await settle(600);
  await shot("03b-profitability-quadrant-filtered");
  await measure();

  // 4 Store profitability
  await page.goto(`${BASE}/profitability?${Q}`);
  await page.waitForSelector('[data-testid="dot-rohini"]');
  await page.click('[data-testid="dot-rohini"]');
  await page.waitForSelector('[data-testid="bar-gm_var"]');
  await settle(1100);
  await shot("04-store-profitability");
  await shot("04-store-profitability-full", true);
  await measure();

  // 5 Cash & Working Capital
  await page.goto(`${BASE}/cash?${Q}`);
  await page.waitForSelector('[data-testid="cash-bridge"] [data-testid^="bar-"]');
  await settle(1100);
  await shot("05-cash-working-capital");
  await shot("05-cash-working-capital-full", true);
  await measure();

  // 6-8 investigation drawer, ledger, voucher (store path)
  await page.goto(`${BASE}/profitability?${Q}`);
  await page.waitForSelector('[data-testid="dot-rohini"]');
  const names = { store: "x", "movement-drawer": "06-investigation-drawer", "driver-department": "06b-drawer-driver", "gl-account": "06c-drawer-gl-account", ledger: "07-ledger", voucher: "08-voucher-evidence" };
  await profitDrill(page, async (k) => {
    if (names[k] !== "x") await shot(names[k]);
    await measure();
  });

  // cash drawer too
  await page.goto(`${BASE}/cash?${Q}`);
  await page.waitForSelector('[data-testid="driver-inventory"]');
  await page.click('[data-testid="driver-inventory"]');
  await page.waitForSelector('[data-testid="investigation-drawer"] [data-testid="drill-rows"]');
  await settle(600);
  await shot("06d-cash-drawer");
  await measure();

  report[tag] = checks;
  await ctx.close();
}

/* two end-to-end journeys, recorded at 1440x900 */
async function journey(name, steps) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: DEMO, size: { width: 1440, height: 900 } } });
  const page = await ctx.newPage();
  const vid = page.video();
  let n = 0;
  const frame = async (label) => {
    n += 1;
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${DEMO}${name}-${String(n).padStart(2, "0")}-${label}.png` });
  };
  await steps(page, frame);
  await page.waitForTimeout(800);
  await ctx.close();
  renameSync(await vid.path(), `${DEMO}${name}.webm`);
}

await journey("journey-A-profitability", async (page, frame) => {
  await page.goto(`${BASE}/?${Q}`);
  await page.waitForSelector('[data-testid="pulse-cash"]');
  await frame("command-center");
  await page.click('[data-testid="nav-profitability"]');
  await page.waitForSelector('[data-testid="dot-rohini"]');
  await frame("profitability");
  await page.click('[data-testid="quadrant-turnaround"]');
  await frame("quadrant-filter");
  await page.click('[data-testid="dot-rohini"]');
  await page.waitForSelector('[data-testid="bar-gm_var"]');
  await frame("store");
  await page.click('[data-testid="bar-gm_var"]');
  await page.waitForSelector('[data-testid="investigation-drawer"] [data-testid="drill-rows"]');
  await frame("driver-drawer");
  await page.click('[data-testid="split-tab-Account"]');
  await page.click('[data-testid="investigation-drawer"] [data-testid^="drill-row-Account:"] >> nth=0');
  await page.waitForSelector('[data-testid="drawer-terminal"]');
  await frame("gl-account");
  await page.click('[data-testid="open-ledger"]');
  await page.waitForSelector('[data-testid="ledger-table"]');
  await frame("ledger");
  await page.click('[data-testid="ledger-row-E2"]');
  await page.waitForSelector('[data-testid="evidence"]');
  await frame("voucher");
  await page.click('[data-testid="deep-back"]');
  await page.waitForSelector('[data-testid="ledger-table"]');
  await frame("back-to-ledger");
  await page.click('[data-testid="deep-back"]');
  await page.waitForSelector('[data-testid="investigation-drawer"]');
  await frame("back-to-account");
});

await journey("journey-B-creditors", async (page, frame) => {
  await page.goto(`${BASE}/?${Q}`);
  await page.waitForSelector('[data-testid="pulse-creditors"]');
  await frame("command-center");
  await page.click('[data-testid="nav-creditors"]');
  await page.waitForSelector('[data-testid="river-b0_30"]');
  await frame("creditors");
  await page.click('[data-testid="river-b181_365"]');
  await frame("ageing-bucket");
  await page.click('[data-testid="lens-concentration"]');
  await page.waitForTimeout(500);
  await page.click('[data-testid^="vendor-V"] >> nth=0');
  await page.waitForSelector('[data-testid="vendor-profile"] [data-testid="lifecycle"]');
  await frame("vendor");
  await page.click('[data-testid="vendor-open-ledger"]');
  await page.waitForSelector('[data-testid="ledger-table"]');
  await frame("ledger");
  await page.click('[data-testid="ledger-row-E2"]');
  await page.waitForSelector('[data-testid="evidence"]');
  await frame("voucher");
});

await browser.close();
writeFileSync(`${OUT}layout-report.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
