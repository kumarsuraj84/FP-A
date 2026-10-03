# CityKart CFO Operating System — frontend (Stage 1: CFO Command Center)

Demo data only. The banner reads **"Demo data — financial source reconciliation pending"**; nothing here is labelled live.

## Run

```bash
npm install
npm run dev          # http://localhost:5180 (pass --port 5180)
npm test             # 40 tests (state machine, data contracts, UI journey)
npm run typecheck
npm run build
node scripts/screenshots.mjs   # regenerates docs/screenshots at 1920x1080 and 1440x900
```

## Journey

`Summary → Movement → Driver → Entity → Ledger → Voucher / source evidence`

| Level | Where | Opens from |
|---|---|---|
| Summary | Financial Pulse strip | — |
| Movement | Hero bridge bar, liquidity stat, working-capital row, risk pillar, attention CTA, forecast bridge bar | click |
| Driver / Entity | Investigation **drawer** (split tabs, supporting drivers) | click any row |
| Entity profile | Full page `/profile` | drawer terminal → "Open … profile" |
| Ledger | Full page `/ledger` | drawer terminal → "Open ledger" |
| Voucher / evidence | Full page `/voucher` | ledger row |

Breadcrumbs are clickable at every level. Period, comparison, scenario, data state and hero tab live outside the drill path, so going back never resets them. State is mirrored to `sessionStorage`.

## Architecture

- `src/types/cfo.ts` — typed contracts (`CfoApi`, envelopes, drill model).
- `src/api/` — `mockApi` (default) and `httpApi` (same interface, used when `VITE_API_BASE_URL` is set); `hooks.ts` are the only data entry points for components.
- `src/mocks/` — scenario parameters, builders and the drill engine. All numbers originate here, never in components.
- `src/context/` — `cfoState.ts` (pure reducer, unit tested) and `CfoContext.tsx` (URL/browser-Back sync).
- `src/components/cfo/` — shell, pulse, hero, drawer, cash story, risk, actions, forecast, deep pages.

Scenarios: Normal, Cash Pressure, Aged Creditors, Vendor Advance Risk, Margin Pressure. Data states (demo control in the banner): normal, stale, unavailable, error, empty. Missing values render `—` with a reason such as "Awaiting finance mapping", never zero.

Future destinations in the left nav are visibly disabled (Stage 2+).
