# CityKart CFO Operating System — frontend (Stage 1: CFO Command Center)

Demo data only. The banner reads **"Demo data — financial source reconciliation pending"**; nothing here is labelled live.

## Run

```bash
npm install
npm run dev          # http://localhost:5180 (pass --port 5180)
npm test             # 64 tests (state machine, URL state, data contracts, UI journey)
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

## Shareable investigation links

The analytical state lives in the URL. Refreshing, copying the link, or opening it elsewhere restores the same investigation.

```
/?period=ytdfy27&compare=budget&scenario=normal&drill=hero:profit.gm_impact/Department:Menswear/Region:North/Store:Rohini
/ledger?...&drill=hero:profit.gm_impact/Department:Menswear/Region:North/Store:Rohini/ledger
/voucher?...&drill=.../ledger/voucher:JV-26-007429
```

- `period`, `compare`, `scenario` are always explicit; `tab`, `horizon`, `data` appear only when not default.
- `drill` is `<scope>.<originId>` then one segment per node (`Dim:Label`, `ledger`, `profile`, `voucher:<id>`).
- Amounts are not in the URL. A link is resolved by replaying the path through the API, so it always shows current numbers. If a step no longer exists (stale or edited link) the app lands on the command center with the same filters.
- Each drill step pushes a history entry (browser Back unwinds it); filter changes replace the entry. `src/context/drillUrl.ts` holds the encode/decode/resolve logic; `CfoContext.tsx` keeps URL and state in sync with a canonical key so they cannot loop.
- Verify in a real browser: `node scripts/url-e2e.mjs` (dev server on :5180).

Breadcrumbs are clickable at every level. Period, comparison, scenario, data state and hero tab live outside the drill path, so going back never resets them. 

## Architecture

- `src/types/cfo.ts` — typed contracts (`CfoApi`, envelopes, drill model).
- `src/api/` — `mockApi` (default) and `httpApi` (same interface, used when `VITE_API_BASE_URL` is set); `hooks.ts` are the only data entry points for components.
- `src/mocks/` — scenario parameters, builders and the drill engine. All numbers originate here, never in components.
- `src/context/` — `cfoState.ts` (pure reducer, unit tested) and `CfoContext.tsx` (URL/browser-Back sync).
- `src/components/cfo/` — shell, pulse, hero, drawer, cash story, risk, actions, forecast, deep pages.

Scenarios: Normal, Cash Pressure, Aged Creditors, Vendor Advance Risk, Margin Pressure. Data states (demo control in the banner): normal, stale, unavailable, error, empty. Missing values render `—` with a reason such as "Awaiting finance mapping", never zero.

Future destinations in the left nav are visibly disabled (Stage 2+).
