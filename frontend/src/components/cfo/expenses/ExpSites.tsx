import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, CheckCircle2, Download, XCircle } from "lucide-react";
import { useExpSites } from "@/api/expensesLiveHooks";
import { DASH, fmtDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ExpMode, ExpQuery, ExpScope, ExpSite, ExpSites } from "@/types/expensesLive";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { cr2, dashReason, downloadCsv, monthShort, pct1 } from "../mgmt/mgmtFormat";
import type { ExpSearch } from "./expensesUrl";

type SortKey = "name" | "net_sales" | "value" | "pct" | "vs_peer" | "sqft" | "rank" | "mom" | "share";

const FLAG_STYLE: Record<string, string> = {
  nso_ty: "border-[oklch(0.75_0.08_265)] bg-[oklch(0.96_0.03_265)] text-[oklch(0.35_0.1_265)]",
  above_peer: "border-[oklch(0.78_0.12_25)] bg-[oklch(0.97_0.03_25)] text-[oklch(0.45_0.15_25)]",
  mom_jump: "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] text-[oklch(0.45_0.09_75)]",
  net_credit: "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] text-[oklch(0.45_0.09_75)]",
};
const FLAG_SHORT: Record<string, string> = { nso_ty: "NSO TY", above_peer: "Above peers", mom_jump: "MoM jump", no_sales: "No sales", net_credit: "Net credit", no_area: "No area" };
const SHOWN_FLAGS = ["nso_ty", "above_peer", "mom_jump", "no_sales", "net_credit"];

/** The figure a row shows for the chosen head and mode. */
const valueOf = (r: ExpSite, head: string, mode: ExpMode) => (head ? r.heads[head]?.[mode] ?? 0 : mode === "book" ? r.book : mode === "adjustment" ? r.adjustment : r.total);
const pctOf = (r: ExpSite, head: string) => (head ? r.pct_ns_heads[head] ?? null : r.pct_ns);

function Row({ r, d, head, mode, scope, selected, onPick, peerMedian }: { r: ExpSite; d: ExpSites; head: string; mode: ExpMode; scope: ExpScope; selected: boolean; onPick: (r: ExpSite) => void; peerMedian: number | null }) {
  const v = valueOf(r, head, mode);
  const pc = pctOf(r, head);
  const vs = scope === "store" && pc !== null && peerMedian !== null ? pc - peerMedian : scope !== "store" ? null : null;
  return (
    <tr data-testid={`site-${r.key}`} data-selected={selected} data-flags={r.flags.map((f) => f.code).join(" ")} className={cn("border-b hover:bg-muted/40", selected && "bg-[oklch(0.96_0.03_265)]")}>
      <th scope="row" className="sticky left-0 z-10 whitespace-nowrap border-r bg-card px-3 py-1.5 text-left font-normal">
        <button type="button" data-testid={`open-site-${r.key}`} onClick={() => onPick(r)} className="press text-left text-primary underline-offset-2 hover:underline">{r.short_name ?? r.name ?? `Site ${r.site_code}`}</button>
        <span className="ml-2 text-[10.5px] text-muted-foreground">{r.site_code}</span>
        {scope !== "store" && <span className="ml-1.5 rounded-sm border px-1 text-[10px] uppercase tracking-wide text-muted-foreground">{r.entity === "HOLDCO" ? "HoldCo" : "SubCo"}</span>}
      </th>
      {scope === "store" && <td className="whitespace-nowrap px-3 py-1.5 text-muted-foreground" title={r.opening_date ? `Opened ${fmtDate(r.opening_date)}` : undefined}>{r.store_type ?? DASH}</td>}
      {scope === "store" && <td className="num-mono whitespace-nowrap px-3 py-1.5 text-right">{r.net_sales === null ? <span title={dashReason("value", "Revenue from operations are only read for SubCo stores")}>{DASH}</span> : cr2(r.net_sales)}</td>}
      <td data-exact={String(v)} className="num-mono whitespace-nowrap px-3 py-1.5 text-right font-medium">{cr2(v)}</td>
      {scope === "store" && <td className="num-mono whitespace-nowrap px-3 py-1.5 text-right">{pc === null ? <span title={dashReason("pct", "No revenue from operations in the period, so no % of revenue")}>{DASH}</span> : pct1(pc)}</td>}
      {scope === "store" && (
        <td className={cn("num-mono whitespace-nowrap px-3 py-1.5 text-right", vs !== null && vs > 0.5 && "tone-bad")} title={vs === null ? dashReason("value", "No peer comparison without revenue from operations") : `Peer median ${pct1(peerMedian)}`}>
          {vs === null ? DASH : `${vs > 0 ? "+" : vs < 0 ? "−" : ""}${Math.abs(vs).toFixed(1)} pp`}
        </td>
      )}
      {scope !== "store" && <td className="num-mono whitespace-nowrap px-3 py-1.5 text-right" title="Total divided by the median total of the sites of this scope">{r.vs_peer_ratio === null ? DASH : `${r.vs_peer_ratio.toFixed(2)}×`}</td>}
      <td className="num-mono whitespace-nowrap px-3 py-1.5 text-right" title={r.per_sqft_month === null ? dashReason("value", d.area_note) : "INR per sq ft per month"}>{r.per_sqft_month === null ? DASH : r.per_sqft_month.toFixed(0)}</td>
      <td className="num whitespace-nowrap px-3 py-1.5 text-right text-muted-foreground">{r.rank ?? DASH}</td>
      <td className={cn("num-mono whitespace-nowrap px-3 py-1.5 text-right", r.mom_pct !== null && r.mom_pct > 20 && "tone-bad")} title={r.mom_pct === null ? dashReason("value", "No expense in the month before") : `${cr2(r.prev_month)} to ${cr2(r.last_month)}`}>{r.mom_pct === null ? DASH : pct1(r.mom_pct)}</td>
      <td className="px-3 py-1.5">
        <span className="flex flex-wrap gap-1">
          {r.flags.filter((f) => SHOWN_FLAGS.includes(f.code)).map((f) => (
            <span key={f.code} title={f.text} data-testid={`flag-${f.code}`} className={cn("rounded-sm border px-1 text-[10.5px] font-semibold", FLAG_STYLE[f.code] ?? "border-border bg-muted text-muted-foreground")}>{FLAG_SHORT[f.code] ?? f.code}</span>
          ))}
        </span>
      </td>
    </tr>
  );
}

/** Stores (or DC / HO sites) ranked, with search, sort, flag filter and a peer comparison. A click opens the site's ledgers in the drill. */
export function ExpSitesPanel({ q, scope, mode, s, onPick, headLabels }: { q: ExpQuery; scope: ExpScope; mode: ExpMode; s: ExpSearch; onPick: (r: ExpSite) => void; headLabels: Record<string, string> }) {
  const sites = useExpSites(q);
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "value", dir: "desc" });
  const [find, setFind] = useState("");
  const [flag, setFlag] = useState("");
  const [type, setType] = useState("");
  const [head, setHead] = useState("");
  const th = "whitespace-nowrap px-3 py-2 font-semibold";
  const data = sites.data;
  const body = useMemo(() => {
    if (!data) return null;
    const needle = find.trim().toLowerCase();
    const med = data.peer.heads[head]?.median_pct ?? null;
    const peerMedian = head ? med : data.peer.median_pct ?? null;
    const localRank = new Map<string, number>();
    if (head) [...data.sites].filter((r) => r.net_sales && pctOf(r, head) !== null).sort((a, b) => (pctOf(b, head) ?? 0) - (pctOf(a, head) ?? 0)).forEach((r, i) => localRank.set(r.key, i + 1));
    const view = data.sites.map((r) => (head ? { ...r, rank: localRank.get(r.key) ?? null } : r));
    const rows = view
      .filter((r) => (!flag || r.flags.some((f) => f.code === flag)) && (!type || r.store_type === type) && (!needle || [r.short_name, r.name, String(r.site_code)].some((x) => (x ?? "").toLowerCase().includes(needle))))
      .sort((a, b) => {
        const f = (r: ExpSite): number | string | null =>
          sort.key === "name" ? (r.short_name ?? r.name ?? "") : sort.key === "net_sales" ? r.net_sales : sort.key === "value" ? valueOf(r, head, mode) : sort.key === "pct" ? pctOf(r, head)
          : sort.key === "vs_peer" ? (scope === "store" ? (pctOf(r, head) !== null && peerMedian !== null ? (pctOf(r, head) as number) - peerMedian : null) : r.vs_peer_ratio) : sort.key === "sqft" ? r.per_sqft_month : sort.key === "rank" ? r.rank : sort.key === "mom" ? r.mom_pct : r.share_pct;
        const av = f(a);
        const bv = f(b);
        if (av === null && bv === null) return 0;
        if (av === null) return 1;
        if (bv === null) return -1;
        const c = typeof av === "string" ? av.localeCompare(bv as string) : (av as number) - (bv as number);
        return sort.dir === "asc" ? c : -c;
      });
    return { rows, peerMedian };
  }, [data, find, flag, type, head, mode, sort, scope]);
  const types = [...new Set((data?.sites ?? []).map((r) => r.store_type).filter((x): x is string => !!x))].sort();
  const sortBtn = (key: SortKey, label: string, right = true, hint?: string) => (
    <th scope="col" aria-sort={sort.key === key ? (sort.dir === "asc" ? "ascending" : "descending") : "none"} title={hint} className={cn(th, right && "text-right")}>
      <button type="button" data-testid={`sites-sort-${key}`} onClick={() => setSort((x) => (x.key === key ? { key, dir: x.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "name" || key === "rank" ? "asc" : "desc" }))} className="press inline-flex items-center gap-1 uppercase tracking-wider hover:text-foreground">
        {label}{sort.key === key && (sort.dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  );
  const csv = (d: ExpSites) => {
    const rows = body?.rows ?? [];
    downloadCsv(`${scope}-expenses-sites-${d.from_month}_${d.to_month}.csv`, [["Site", "Code", "Entity", "Revenue from operations", mode, "% of revenue", "Per sq ft per month", "Rank", "MoM %", "Flags"], ...rows.map((r) => [r.short_name ?? r.name ?? "", r.site_code, r.entity, r.net_sales ?? "", valueOf(r, head, mode), pctOf(r, head) ?? "", r.per_sqft_month ?? "", r.rank ?? "", r.mom_pct ?? "", r.flags.map((f) => f.code).join(" ")])]);
  };
  const inputCls = "h-7 rounded border bg-card px-1.5 text-[12px]";
  return (
    <Panel
      testId="exp-sites"
      eyebrow={scope === "store" ? "Stores" : "Sites"}
      title={scope === "store" ? "Stores ranked by expense (INR Cr)" : "DC sites ranked by expense (INR Cr)"}
      right={
        data && (
          <div className="flex items-center gap-2">
            <span data-testid="sites-reconciles" data-ok={String(data.reconciles)} title={`Sites add to ${cr2(data.children_sum.total)}; unallocated ${cr2(data.unallocated.total)}. ${data.unallocated.note}`} className={cn("inline-flex items-center gap-1 text-[11.5px]", data.reconciles ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}>
              {data.reconciles ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}{data.reconciles ? "Sites add up to the total" : "Sites do not add up"}
            </span>
            <button type="button" data-testid="sites-export" onClick={() => csv(data)} className="press inline-flex items-center gap-1 rounded border px-2 py-1 text-[12px] font-medium hover:bg-muted"><Download className="h-3.5 w-3.5" /> CSV</button>
          </div>
        )
      }
    >
      <LiveBoundary query={sites} skeleton={<Skeleton className="m-4 h-[320px]" />}>
        {(d) => (
          <>
            <div data-testid="sites-controls" className="flex flex-wrap items-center gap-3 border-b px-4 py-2 text-[12px]">
              <label className="flex items-center gap-1"><span className="eyebrow">Find</span><input data-testid="sites-search" aria-label="Find a site" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Name or site code" className={cn(inputCls, "w-40")} /></label>
              <label className="flex items-center gap-1"><span className="eyebrow">Head</span>
                <select data-testid="sites-head" aria-label="Expense head" value={head} onChange={(e) => setHead(e.target.value)} className={inputCls}>
                  <option value="">All heads</option>
                  {Object.entries(headLabels).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </label>
              <label className="flex items-center gap-1"><span className="eyebrow">Flag</span>
                <select data-testid="sites-flag" aria-label="Flag" value={flag} onChange={(e) => setFlag(e.target.value)} className={inputCls}>
                  <option value="">All</option>
                  {SHOWN_FLAGS.map((f) => <option key={f} value={f}>{FLAG_SHORT[f]}</option>)}
                </select>
              </label>
              {scope === "store" && types.length > 0 && (
                <label className="flex items-center gap-1"><span className="eyebrow">Type</span>
                  <select data-testid="sites-type" aria-label="Store type" value={type} onChange={(e) => setType(e.target.value)} className={inputCls}>
                    <option value="">All</option>
                    {types.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </label>
              )}
              <span className="ml-auto text-[11.5px] text-muted-foreground" data-testid="sites-peer" title={d.peer.method}>
                {scope === "store"
                  ? `Peer median ${pct1(body?.peerMedian ?? null)} of revenue from operations · 90th percentile ${pct1(head ? d.peer.heads[head]?.p90_pct ?? null : d.peer.p90_pct ?? null)} · ${d.peer.n} peer stores`
                  : `Median site ${cr2(d.peer.median_cr ?? null)} Cr · ${d.peer.n} sites`}
              </span>
            </div>
            <div className="max-h-[70vh] overflow-auto">
              <table className="w-full min-w-[900px] border-separate border-spacing-0 text-[12.5px]" data-testid="sites-table">
                <thead className="sticky top-0 z-20 bg-card text-left text-[10.5px] text-muted-foreground">
                  <tr className="border-b">
                    <th scope="col" className={cn(th, "sticky left-0 z-30 border-b border-r bg-card")} aria-sort={sort.key === "name" ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
                      <button type="button" data-testid="sites-sort-name" onClick={() => setSort((x) => (x.key === "name" ? { key: "name", dir: x.dir === "asc" ? "desc" : "asc" } : { key: "name", dir: "asc" }))} className="press inline-flex items-center gap-1 uppercase tracking-wider hover:text-foreground">
                        {scope === "store" ? "Store" : "Site"}{sort.key === "name" && (sort.dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                      </button>
                    </th>
                    {scope === "store" && <th scope="col" className={th}>Type</th>}
                    {scope === "store" && sortBtn("net_sales", "Revenue from operations")}
                    {sortBtn("value", `Expense (${mode})`, true, head ? headLabels[head] : "All heads")}
                    {scope === "store" && sortBtn("pct", "% of revenue")}
                    {sortBtn("vs_peer", scope === "store" ? "vs peer median" : "vs median site", true, scope === "store" ? "Percentage points above (+) or below (−) the peer median" : "Total divided by the median total of the DC sites")}
                    {sortBtn("sqft", "Per sq ft / mo", true, d.area_note)}
                    {sortBtn("rank", "Rank", true, "1 = the highest expense " + (scope === "store" ? "as % of revenue" : "of the sites"))}
                    {sortBtn("mom", `MoM (${monthShort(d.to_month)})`, true, "Latest month against the month before")}
                    <th scope="col" className={th}>Flags</th>
                  </tr>
                </thead>
                <tbody>
                  {(body?.rows ?? []).map((r) => (
                    <Row key={r.key} r={r} d={d} head={head} mode={mode} scope={scope} selected={s.site === r.site_code && (s.se ?? (scope === "store" ? "SUBCO" : r.entity)) === r.entity} onPick={onPick} peerMedian={body?.peerMedian ?? null} />
                  ))}
                  {(body?.rows.length ?? 0) === 0 && <tr><td colSpan={10} data-testid="sites-empty" className="px-4 py-6 text-center text-muted-foreground">{d.sites.length === 0 ? "No site posts expense for this period and entity." : "No site matches the filter."}</td></tr>}
                </tbody>
                <tfoot className="sticky bottom-0 z-20 bg-secondary font-semibold">
                  <tr data-testid="sites-total">
                    <th scope="row" className="sticky left-0 z-30 whitespace-nowrap border-r bg-secondary px-3 py-2 text-left">{(body?.rows.length ?? 0) === d.sites.length ? `Total (${d.sites.length} ${scope === "store" ? "stores" : "sites"})` : `Total (${body?.rows.length ?? 0} of ${d.sites.length})`}</th>
                    {scope === "store" && <td />}
                    {scope === "store" && <td className="num-mono px-3 py-2 text-right">{cr2((body?.rows ?? []).reduce((t, r) => t + (r.net_sales ?? 0), 0))}</td>}
                    <td data-testid="sites-total-value" data-exact={(body?.rows ?? []).reduce((t, r) => t + valueOf(r, head, mode), 0).toFixed(4)} className="num-mono px-3 py-2 text-right">{cr2((body?.rows ?? []).reduce((t, r) => t + valueOf(r, head, mode), 0))}</td>
                    <td colSpan={scope === "store" ? 6 : 5} className="px-3 py-2 text-right text-[11.5px] font-normal text-muted-foreground">{d.unallocated.total !== 0 ? `Not attributable to a site: ${cr2(d.unallocated.total)} (management adjustments)` : ""}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <div className="border-t px-4 py-2 text-[11.5px] text-muted-foreground" data-testid="sites-footnote">
              {d.peer.method} {scope === "store" ? "Store-level management adjustments are allocated to stores pro rata to revenue from operations, as the store league does." : "DC and HO adjustments are not attributable to one site."} {d.area_note}
            </div>
          </>
        )}
      </LiveBoundary>
    </Panel>
  );
}
