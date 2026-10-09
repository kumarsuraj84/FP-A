import { Fragment, useState } from "react";
import { ArrowDown, ArrowUp, CheckCircle2, Download, XCircle } from "lucide-react";
import { useMgmtStores } from "@/api/mgmtLiveHooks";
import { DASH, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { MgmtStoreRow, MgmtStores } from "@/types/mgmtLive";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { MgmtFrame, MonthRange } from "./MgmtFrame";
import { useMgmtEntity } from "./mgmtEntity";
import { cr2, dashReason, downloadCsv, monthShort, ratePct, toneOf } from "./mgmtFormat";
import { isPartialMonth, lastCompleteMonth } from "./mgmtMonths";

type NumKey = "net_sales" | "rgm" | "store_expenses" | "four_wall" | "apportioned" | "ebitda_after";
type SortKey = NumKey | "store";

const COLS: { key: NumKey; label: string; hint: string }[] = [
  { key: "net_sales", label: "Revenue from operations", hint: "Revenue from operations, ex-GST" },
  { key: "rgm", label: "Gross Margin", hint: "Revenue from operations plus other operating income less Material Cost, for one store" },
  { key: "store_expenses", label: "Store Expenses", hint: "Rent, employee, power, advertisement, freight and other store expenses" },
  { key: "four_wall", label: "4-Wall EBITDA", hint: "Gross Margin less Store Expenses: what the store earns before DC and HO cost" },
  { key: "apportioned", label: "DC + HO", hint: "DC and HO cost spread pro rata to revenue from operations at one blended rate" },
  { key: "ebitda_after", label: "EBITDA after DC & HO", hint: "4-Wall EBITDA less the apportioned DC and HO cost" },
];

const TOL = 0.011; // INR Cr: the sheet rounds each store to two decimals

const sumOf = (rows: MgmtStoreRow[], k: NumKey) => rows.reduce((s, r) => s + (r[k] ?? 0), 0);

/** Row sums against the summary the API sends for the same scope: the page does not trust the API's own `reconciles` alone. */
export function checkStores(d: MgmtStores): { ok: boolean; problems: string[] } {
  const problems: string[] = [];
  const pairs: [NumKey, number][] = [["net_sales", d.summary.net_sales], ["rgm", d.summary.rgm], ["store_expenses", d.summary.store_expenses], ["four_wall", d.summary.four_wall], ["apportioned", d.summary.apportioned], ["ebitda_after", d.summary.store_ebitda_after]];
  for (const [k, v] of pairs) if (Math.abs(sumOf(d.rows, k) - v) > TOL) problems.push(`${COLS.find((c) => c.key === k)!.label}: stores add to ${cr2(sumOf(d.rows, k))}, summary says ${cr2(v)}`);
  if (Math.abs(d.summary.apportioned - (d.summary.dc_total + d.summary.ho_total)) > TOL) problems.push(`Apportioned ${cr2(d.summary.apportioned)} is not DC ${cr2(d.summary.dc_total)} + HO ${cr2(d.summary.ho_total)}`);
  if (Math.abs(d.summary.four_wall - (d.summary.rgm + d.summary.store_expenses)) > TOL) problems.push("4-Wall EBITDA is not Gross Margin + Store Expenses");
  if (!d.summary.reconciles) problems.push("The API reports that the stores do not reconcile to the P&L");
  return { ok: problems.length === 0, problems };
}

function StoresBody({ months, asOf }: { months: string[]; asOf: string }) {
  // default: the last COMPLETE month; a partial month can be chosen and is labelled
  const [from, setFrom] = useState(lastCompleteMonth(months, asOf));
  const [to, setTo] = useState(lastCompleteMonth(months, asOf));
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "net_sales", dir: "desc" });
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const entity = useMgmtEntity();
  const stores = useMgmtStores(from || undefined, to || undefined, entity);
  return (
    <>
      <div data-testid="mgmt-controls" className="flex flex-wrap items-center gap-3 border-b bg-card px-5 py-2 text-[12px]">
        <MonthRange months={months} from={from} to={to} asOf={asOf} onChange={(f, t) => { setFrom(f); setTo(t); }} />
        <div className="mx-1 h-5 w-px bg-border" />
        <label className="flex items-center gap-1">
          <span className="eyebrow">Find</span>
          <input data-testid="stores-search" aria-label="Find a store" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Store or site code" className="h-7 w-44 rounded border bg-card px-2 text-[12px]" />
        </label>
        <label className="flex items-center gap-1">
          <span className="eyebrow">Type</span>
          <select data-testid="stores-type" aria-label="Store type" value={type} onChange={(e) => setType(e.target.value)} className="h-7 rounded border bg-card px-1.5 text-[12px]">
            <option value="">All</option>
            {[...new Set((stores.data?.rows ?? []).map((r) => r.store_type).filter((x): x is string => !!x))].sort().map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
      </div>
      <LiveBoundary query={stores} skeleton={<Skeleton className="m-4 h-[420px]" />}>
        {(d) => {
          const check = checkStores(d);
          const pctRate = ratePct(d.rate);
          const needle = search.trim().toLowerCase();
          const rows = d.rows
            .filter((r) => (!type || r.store_type === type) && (!needle || r.store.toLowerCase().includes(needle) || r.site_code.toLowerCase().includes(needle)))
            .sort((a, b) => {
              if (sort.key === "store") return sort.dir === "asc" ? a.store.localeCompare(b.store) : b.store.localeCompare(a.store);
              const av = a[sort.key];
              const bv = b[sort.key];
              if (av === null && bv === null) return 0;
              if (av === null) return 1; // blanks sort last in either direction
              if (bv === null) return -1;
              return sort.dir === "asc" ? av - bv : bv - av;
            });
          const filtered = rows.length !== d.rows.length;
          const th = "whitespace-nowrap px-3 py-2 font-semibold";
          const head = (key: SortKey, label: string, hint?: string, right = true) => (
            <th scope="col" aria-sort={sort.key === key ? (sort.dir === "asc" ? "ascending" : "descending") : "none"} title={hint} className={cn(th, right && "text-right")}>
              <button type="button" data-testid={`sort-${key}`} onClick={() => setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "store" ? "asc" : "desc" }))} className="press inline-flex items-center gap-1 uppercase tracking-wider hover:text-foreground">
                {label}
                {sort.key === key && (sort.dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
              </button>
            </th>
          );
          const totals = Object.fromEntries(COLS.map((c) => [c.key, sumOf(rows, c.key)])) as Record<NumKey, number>;
          return (
            <>
              <section aria-label="Apportionment" data-testid="stores-rate" className="grid grid-cols-[auto_1fr] items-center gap-x-6 gap-y-1 border-b bg-card px-5 py-3 @max-[800px]:grid-cols-1">
                <div>
                  <div className="eyebrow">Blended DC + HO rate</div>
                  <div data-testid="stores-rate-value" data-exact={String(d.rate)} className="num-mono text-[24px] font-semibold leading-tight">{fmtPct(pctRate, { digits: 2 })}</div>
                  <div className="num text-[11.5px] text-muted-foreground">of every store's revenue from operations · {monthShort(from)}{from !== to ? ` to ${monthShort(to)}` : ""}{isPartialMonth(to, asOf) && <span data-testid="stores-partial" className="ml-1 font-semibold text-[oklch(0.45_0.09_75)]">· {monthShort(to)} is a partial month (data to {asOf.slice(8, 10)}/{asOf.slice(5, 7)})</span>}</div>
                </div>
                <p data-testid="stores-rate-note" className="max-w-3xl text-[12px] text-muted-foreground">
                  DC cost ({cr2(d.summary.dc_total)}) plus HO cost ({cr2(d.summary.ho_total)}) is spread over the stores pro rata to revenue from operations, at this one rate, exactly as the finance MIS does. Area, footfall and actual DC usage play no part, so a small or new store carries the same share as a large one.
                </p>
              </section>
              <div className="p-3">
                <Panel
                  testId="stores-panel"
                  eyebrow="Real · management view"
                  title="Store league: 4-Wall EBITDA and EBITDA after DC & HO (INR Cr)"
                  right={
                    <div className="flex items-center gap-2">
                      <span data-testid="stores-reconciles" data-ok={check.ok} title={check.problems.join("\n")} className={cn("inline-flex items-center gap-1 text-[11.5px]", check.ok ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}>
                        {check.ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                        {check.ok ? "Stores add up to the P&L" : "Stores do not add up to the P&L"}
                      </span>
                      <button
                        type="button"
                        data-testid="stores-export"
                        className="press inline-flex items-center gap-1 rounded border px-2 py-1 text-[12px] font-medium hover:bg-muted"
                        onClick={() => downloadCsv(`mgmt-stores-${d.run_id}-${from}${from !== to ? `_${to}` : ""}.csv`, [["Store", "Site", "Type", ...COLS.map((c) => c.label)], ...rows.map((r) => [r.store, r.site_code, r.store_type ?? "", ...COLS.map((c) => r[c.key] ?? "")]), ["Total", "", "", ...COLS.map((c) => totals[c.key].toFixed(4))]])}
                      >
                        <Download className="h-3.5 w-3.5" /> CSV
                      </button>
                    </div>
                  }
                >
                  {!check.ok && <div data-testid="stores-problems" className="border-b bg-[oklch(0.97_0.03_25)] px-4 py-1.5 text-[11.5px] tone-bad">{check.problems.join(" · ")}</div>}
                  <div className="max-h-[70vh] overflow-auto">
                    <table className="w-full min-w-[820px] border-separate border-spacing-0 text-[12.5px]" data-testid="stores-table">
                      <thead className="sticky top-0 z-20 bg-card text-left text-[10.5px] text-muted-foreground">
                        <tr className="border-b">
                          <th scope="col" className={cn(th, "sticky left-0 z-30 border-b border-r bg-card")} aria-sort={sort.key === "store" ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
                            <button type="button" data-testid="sort-store" onClick={() => setSort((s) => (s.key === "store" ? { key: "store", dir: s.dir === "asc" ? "desc" : "asc" } : { key: "store", dir: "asc" }))} className="press inline-flex items-center gap-1 uppercase tracking-wider hover:text-foreground">
                              Store{sort.key === "store" && (sort.dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                            </button>
                          </th>
                          <th scope="col" className={th}>Type</th>
                          {COLS.map((c) => <Fragment key={c.key}>{head(c.key, c.label, c.hint)}</Fragment>)}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => (
                          <tr key={r.site_code} data-testid={`store-${r.site_code}`} className="border-b hover:bg-muted/40">
                            <th scope="row" className="sticky left-0 z-10 whitespace-nowrap border-b border-r bg-card px-3 py-1.5 text-left font-normal">
                              {r.store}<span className="ml-2 text-[10.5px] text-muted-foreground">{r.site_code}</span>
                            </th>
                            <td className="border-b px-3 py-1.5 text-muted-foreground">{r.store_type ?? DASH}</td>
                            {COLS.map((c) => {
                              const v = r[c.key];
                              return (
                                <td key={c.key} data-exact={v === null ? "" : String(v)} title={v === null ? dashReason("value", "Not reported for this store in the selected months") : undefined} className={cn("num-mono whitespace-nowrap border-b px-3 py-1.5 text-right", toneOf(v))}>
                                  {v === null ? <span className="text-muted-foreground">{DASH}</span> : cr2(v)}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                        {rows.length === 0 && <tr><td colSpan={COLS.length + 2} data-testid="stores-empty" className="px-4 py-6 text-center text-muted-foreground">{d.rows.length === 0 ? "This entity has no stores." : "No store matches the filter."}</td></tr>}
                      </tbody>
                      <tfoot className="sticky bottom-0 z-20 bg-secondary font-semibold">
                        <tr data-testid="stores-total" data-filtered={filtered}>
                          <th scope="row" className="sticky left-0 z-30 whitespace-nowrap border-r bg-secondary px-3 py-2 text-left">
                            {filtered ? `Total (${rows.length} of ${d.rows.length} stores)` : `Total (${d.rows.length} stores)`}
                          </th>
                          <td className="px-3 py-2" />
                          {COLS.map((c) => (
                            <td key={c.key} data-testid={`total-${c.key}`} data-exact={totals[c.key].toFixed(4)} className={cn("num-mono whitespace-nowrap px-3 py-2 text-right", toneOf(totals[c.key]))}>{cr2(totals[c.key])}</td>
                          ))}
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                </Panel>
              </div>
              <div className="px-5 pb-6 text-[11.5px] text-muted-foreground" data-testid="stores-footnote">
                Store EBITDA after DC and HO = 4-Wall EBITDA less the apportioned cost. Company: DC {cr2(d.summary.dc_total)}, HO {cr2(d.summary.ho_total)}, EBITDA after both {cr2(d.summary.store_ebitda_after)}. The NSO subtotal row of the MIS sheet is not a store and is not in this list.
              </div>
            </>
          );
        }}
      </LiveBoundary>
    </>
  );
}


export function MgmtStoresPage() {
  return (
    <MgmtFrame active="stores" subtitle="Per store: revenue from operations, Gross Margin, Store Expenses, 4-Wall EBITDA, and EBITDA after the DC and HO cost apportioned at one blended rate. INR Cr.">
      {(months, _w, asOf) => <StoresBody months={months} asOf={asOf} />}
    </MgmtFrame>
  );
}
