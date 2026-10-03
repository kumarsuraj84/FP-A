// Captures the Stage 1 states at 1920x1080 and 1440x900 and runs layout checks.
// Usage: npm run dev (port 5180), then: node scripts/screenshots.mjs
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
  const checks = { consoleErrors: [], horizontalOverflow: null, clipped: [] };
  page.on("console", (m) => m.type() === "error" && checks.consoleErrors.push(m.text().slice(0, 200)));
  page.on("pageerror", (e) => checks.consoleErrors.push(String(e).slice(0, 200)));

  const settle = () => page.waitForTimeout(900);
  const clipped = () =>
    page.evaluate(() => {
      const bad = [];
      for (const el of document.querySelectorAll("main *, aside *, header *, nav *")) {
        const cs = getComputedStyle(el);
        if (!el.childElementCount && el.textContent && el.textContent.trim() && el.scrollWidth > el.clientWidth + 1 && cs.textOverflow !== "ellipsis" && cs.overflow !== "auto" && !el.closest("svg")) {
          bad.push(`${el.tagName.toLowerCase()}[${(el.getAttribute("data-testid") ?? "")}] "${el.textContent.trim().slice(0, 40)}" ${el.scrollWidth}>${el.clientWidth}`);
        }
      }
      return bad.slice(0, 12);
    });

  await page.goto(BASE + "/");
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await page.waitForSelector('[data-testid="bar-gm_impact"]');
  await settle();
  await page.screenshot({ path: `${OUT}01-command-center-${tag}.png` });
  await page.screenshot({ path: `${OUT}01-command-center-full-${tag}.png`, fullPage: true });
  checks.horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  checks.clipped.push(...(await clipped()));

  // waterfall selected + tooltip + drawer
  await page.hover('[data-testid="bar-gm_impact"]');
  await page.waitForTimeout(250);
  await page.screenshot({ path: `${OUT}02-waterfall-hover-${tag}.png` });
  await page.click('[data-testid="bar-gm_impact"]');
  await page.waitForSelector('[data-testid="drawer-amount"]');
  await page.mouse.move(5, 5);
  await settle();
  await page.screenshot({ path: `${OUT}03-waterfall-selected-drawer-${tag}.png` });
  checks.horizontalOverflow = Math.max(checks.horizontalOverflow, await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth));
  checks.clipped.push(...(await clipped()));

  // deep drill: Menswear > North > Rohini
  await page.click('[data-testid="drill-row-Department:Menswear"]');
  await settle();
  await page.click('[data-testid="split-tab-Region"]');
  await page.click('[data-testid="drill-row-Region:North"]');
  await settle();
  await page.click('[data-testid="split-tab-Store"]');
  await page.click('[data-testid="drill-row-Store:Rohini"]');
  await page.waitForSelector('[data-testid="drawer-terminal"]');
  await settle();
  await page.screenshot({ path: `${OUT}04-deep-drill-entity-${tag}.png` });
  checks.clipped.push(...(await clipped()));

  await page.click('[data-testid="open-ledger"]');
  await page.waitForSelector('[data-testid="ledger-table"]');
  await settle();
  await page.screenshot({ path: `${OUT}05-ledger-${tag}.png` });
  await page.click('[data-testid="ledger-row-E3"]');
  await page.waitForSelector('[data-testid="evidence"]');
  await settle();
  await page.screenshot({ path: `${OUT}06-voucher-evidence-${tag}.png` });
  checks.clipped.push(...(await clipped()));

  // stress scenario + data states
  await page.click('[data-testid="crumb-1"]');
  await page.selectOption('[data-testid="select-scenario"]', "cash_pressure");
  await settle();
  await page.screenshot({ path: `${OUT}07-scenario-cash-pressure-${tag}.png` });
  await page.selectOption('[data-testid="select-datastate"]', "unavailable");
  await settle();
  await page.screenshot({ path: `${OUT}08-state-unavailable-${tag}.png` });

  report[tag] = checks;
  await ctx.close();
}
await browser.close();
writeFileSync(`${OUT}layout-report.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
