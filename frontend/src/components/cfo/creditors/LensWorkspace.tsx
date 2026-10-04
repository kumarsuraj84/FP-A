import { useEffect, useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import { useLiveDocumentAge, useLiveDueStatus, useLiveLedgers, useLiveSummary, useLiveVendors } from "@/api/creditorsLiveHooks";
import { API_TO_BUCKET, fmtRupees, num, toCr, vendorLabel } from "@/api/creditorsLive";
import { useCfo } from "@/context/CfoContext";
import { vendorNode } from "@/lib/creditorNodes";
import { DASH, fmtCr, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AGE_FILTER_LABELS, type BucketId, type Lens } from "@/types/creditors";
import type { LiveVendor } from "@/types/creditorsLive";
import { Skeleton } from "../common";
import { BUCKET_ORDER, LiveBoundary, NotAvailable, bucketColor, useRoomSelection } from "./parts";

const NAVY = "oklch(0.32 0.08 255)";
const API_BUCKETS = ["D0_30", "D31_60", "D61_90", "D91_180", "D181_365", "D365_PLUS"] as const;
const UNCLASSIFIED_COLOR = "oklch(0.8 0.02 260)";

/** What each lens is called on the real page. The lens ids are the URL state and stay as they are. */
const LENS_TABS: { id: Lens; label: string; hint: string }[] = [
  { id: "age", label: "Age", hint: "Where old balances sit" },
  { id: "concentration", label: "Concentration", hint: "Which vendors dominate" },
  { id: "movement", label: "Movement", hint: "What changed since the last snapshot" },
  { id: "abnormal", label: "Debits & gaps", hint: "Debit balances and missing dates, as found" },
];

const over = (v: LiveVendor, keys: readonly string[]) => keys.reduce((a, k) => a + num(v.credit_by_document_age[k]), 0);
const OVER_90 = ["D91_180", "D181_365", "D365_PLUS"] as const;
const OVER_180 = ["D181_365", "D365_PLUS"] as const;

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function useOpenVendor() {
  const { pushNode } = useCfo();
  return (v: LiveVendor) => pushNode(vendorNode(v.vendor_ref, vendorLabel(v), toCr(v.credit_outstanding) ?? 0));
}

function VendorName({ v, rank, onOpen }: { v: LiveVendor; rank: number; onOpen: (v: LiveVendor) => void }) {
  return (
    <button data-testid={`vendor-${v.vendor_ref}`} onClick={() => onOpen(v)} className="press group flex min-w-0 items-center gap-2 text-left" title={v.vendor_name ? `${v.vendor_name} · ${v.vendor_ref}` : v.vendor_ref}>
      <span className="num w-5 shrink-0 text-right text-[11px] text-muted-foreground">{rank}</span>
      <span className={cn("truncate text-[13px] font-medium text-foreground group-hover:underline", !v.vendor_name && "num-mono text-[12px]")}>{vendorLabel(v)}</span>
      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100" />
    </button>
  );
}

/* ───────────── CONCENTRATION: ranked vendors ───────────── */
function ConcentrationView() {
  const { age } = useRoomSelection();
  const sum = useLiveSummary();
  const open = useOpenVendor();
  const [limit, setLimit] = useState(15);
  const [text, setText] = useState("");
  const q = useDebounced(text.trim());
  const vq = useLiveVendors(age, { limit, q: q || undefined });
  const whole = age === "all";
  const cols = "grid-cols-[minmax(0,1.6fr)_minmax(0,3fr)_96px_80px_80px_70px_72px_88px] @max-[1100px]:grid-cols-[minmax(0,1.6fr)_minmax(0,2fr)_96px_88px]";
  const cell = (label: string, value: string, sub?: string, testId?: string) => (
    <div className="px-4 py-2.5" data-testid={testId}>
      <div className="eyebrow">{label}</div>
      <div className="num-mono text-[17px] font-semibold">{value}</div>
      {sub && <div className="truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
  return (
    <div>
      {sum.data && (
        <div className="grid grid-cols-5 divide-x border-b @max-[900px]:grid-cols-3 @max-[900px]:divide-y" data-testid="concentration-indicators">
          {cell("Top 1 share", fmtPct(num(sum.data.credit_concentration.top_1) * 100), "of credit outstanding", "ind-top1")}
          {cell("Top 5 share", fmtPct(num(sum.data.credit_concentration.top_5) * 100), "of credit outstanding", "ind-top5")}
          {cell("Top 10 share", fmtPct(num(sum.data.credit_concentration.top_10) * 100), "of credit outstanding", "ind-top10")}
          {cell("Top 20 share", fmtPct(num(sum.data.credit_concentration.top_20) * 100), "of credit outstanding", "ind-top20")}
          {cell("Vendors with a credit balance", sum.data.credit_vendors.toLocaleString("en-IN"), "stated factually", "ind-count")}
        </div>
      )}
      <LiveBoundary query={vq} skeleton={<Skeleton className="m-4 h-[360px]" />}>
        {(page) => {
          const rows = page.vendors;
          const exposure = (v: LiveVendor) => num(whole ? v.credit_outstanding : v.cohort_credit);
          const max = Math.max(...rows.map(exposure), 1e-9);
          const more = page.total.vendors > rows.length && limit < 500;
          return (
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2 text-[11.5px] text-muted-foreground">
                <span data-testid="vendor-total">
                  {page.total.vendors.toLocaleString("en-IN")} vendor{page.total.vendors === 1 ? "" : "s"}
                  {whole ? "" : ` with credit in ${AGE_FILTER_LABELS[age]}`} · {fmtCr(toCr(whole ? page.total.credit_outstanding : page.total.cohort_credit))}
                </span>
                {page.named ? (
                  <label className="flex items-center gap-1.5 rounded border bg-background px-2 py-1">
                    <Search className="h-3.5 w-3.5" />
                    <input data-testid="vendor-search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Search vendor name" className="w-44 bg-transparent text-[12px] outline-none" />
                  </label>
                ) : (
                  <span data-testid="masked-note" className="rounded-sm bg-muted px-1.5 py-0.5">Vendor names are shown to Finance / CFO access only; this view uses vendor references.</span>
                )}
              </div>
              <div className={cn("grid items-center gap-x-3 px-4 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground", cols)}>
                <span>Vendor</span>
                <span>{whole ? "Credit · by document age" : `Credit in ${AGE_FILTER_LABELS[age]}`}</span>
                <span className="text-right">{whole ? "Credit outstanding" : "In selection"}</span>
                <span className="text-right @max-[1100px]:hidden">&gt;90</span>
                <span className="text-right @max-[1100px]:hidden">&gt;180</span>
                <span className="text-right @max-[1100px]:hidden">% of credit</span>
                <span className="text-right @max-[1100px]:hidden">Oldest</span>
                <span className="text-right">Past due</span>
              </div>
              <ul data-testid="concentration-list">
                {rows.length === 0 && <li className="px-4 py-8 text-center text-[12.5px] text-muted-foreground">No vendors match this selection.</li>}
                {rows.map((v, i) => {
                  const total = num(v.credit_outstanding) || 1;
                  const o90 = over(v, OVER_90);
                  const o180 = over(v, OVER_180);
                  const w = (exposure(v) / max) * 100;
                  const base = whole ? Math.max(0, total - o90) : exposure(v);
                  const mid = whole ? Math.max(0, o90 - o180) : 0;
                  const denom = whole ? total : exposure(v) || 1;
                  return (
                    <li key={v.vendor_ref} className={cn("grid items-center gap-x-3 border-t px-4 py-1.5 hover:bg-[oklch(0.97_0.012_265)]", cols)}>
                      <VendorName v={v} rank={page.offset + i + 1} onOpen={open} />
                      <span className="flex h-3 overflow-hidden rounded-sm bg-muted/60" aria-hidden>
                        <span className="flex h-full" style={{ width: `${w}%` }}>
                          <i style={{ width: `${(base / denom) * 100}%`, background: NAVY }} />
                          <i style={{ width: `${(mid / denom) * 100}%`, background: bucketColor("b91_180") }} />
                          <i style={{ width: `${((whole ? o180 : 0) / denom) * 100}%`, background: bucketColor("b365p") }} />
                        </span>
                      </span>
                      <span data-exact={whole ? v.credit_outstanding : v.cohort_credit} className="num text-right text-[13px] font-semibold">{fmtCr(toCr(whole ? v.credit_outstanding : v.cohort_credit))}</span>
                      <span className="num text-right text-[12px] text-muted-foreground @max-[1100px]:hidden">{o90 > 0.0049 ? fmtCr(o90 / 1e7) : ""}</span>
                      <span className="num text-right text-[12px] text-muted-foreground @max-[1100px]:hidden">{o180 > 0.0049 ? fmtCr(o180 / 1e7) : ""}</span>
                      <span className="num text-right text-[12px] text-muted-foreground @max-[1100px]:hidden">{fmtPct(num(v.share_of_credit) * 100)}</span>
                      <span className="num text-right text-[12px] text-muted-foreground @max-[1100px]:hidden" title="Oldest open credit document, in days since the document date">
                        {v.oldest_credit_age_days === null ? DASH : `${v.oldest_credit_age_days}d`}
                      </span>
                      <span className="num text-right text-[12px] font-semibold" title={fmtRupees(v.past_due_credit)}>{num(v.past_due_credit) > 0 ? fmtCr(toCr(v.past_due_credit)) : <span className="font-normal text-muted-foreground">{DASH}</span>}</span>
                    </li>
                  );
                })}
              </ul>
              <div className="flex items-center justify-between border-t px-4 py-2 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-3">
                  <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm" style={{ background: NAVY }} /> up to 90 days</span>
                  <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm" style={{ background: bucketColor("b91_180") }} /> 91–180</span>
                  <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm" style={{ background: bucketColor("b365p") }} /> &gt;180 (document age)</span>
                </span>
                {more ? (
                  <button data-testid="concentration-toggle" onClick={() => setLimit((l) => Math.min(500, l + 50))} className="press rounded px-2 py-0.5 font-semibold text-primary hover:bg-muted">
                    Show more ({rows.length} of {page.total.vendors.toLocaleString("en-IN")})
                  </button>
                ) : (
                  <span>{rows.length} of {page.total.vendors.toLocaleString("en-IN")} shown</span>
                )}
              </div>
            </div>
          );
        }}
      </LiveBoundary>
    </div>
  );
}

/* ───────────── AGE: where old balances sit ───────────── */
function AgeView() {
  const { age } = useRoomSelection();
  const vq = useLiveVendors(age, { limit: 9 });
  const open = useOpenVendor();
  const whole = age === "all";
  return (
    <LiveBoundary query={vq} skeleton={<Skeleton className="m-4 h-[320px]" />}>
      {(page) => {
        const rows = page.vendors;
        const exposure = (v: LiveVendor) => num(v.credit_outstanding);
        const max = Math.max(...rows.map(exposure), 1e-9);
        return (
          <div className="px-4 py-3" data-testid="age-lens">
            <div className="mb-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
              {BUCKET_ORDER.map((b) => (
                <span key={b} className="flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: bucketColor(b) }} />{AGE_FILTER_LABELS[b]}</span>
              ))}
              <span className="flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: UNCLASSIFIED_COLOR }} />Unclassified</span>
              <span className="ml-auto">Top {rows.length} vendors by {whole ? "credit outstanding" : `credit in ${AGE_FILTER_LABELS[age]}`}</span>
            </div>
            <ul className="space-y-1.5">
              {rows.map((v, i) => (
                <li key={v.vendor_ref} className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,3.2fr)_90px] items-center gap-3">
                  <VendorName v={v} rank={i + 1} onOpen={open} />
                  <span className="flex h-4 overflow-hidden rounded-sm bg-muted/50" aria-hidden>
                    <span className="flex h-full" style={{ width: `${(exposure(v) / max) * 100}%` }}>
                      {API_BUCKETS.map((k) => (
                        <i key={k} title={`${AGE_FILTER_LABELS[API_TO_BUCKET[k] as BucketId]}: ${fmtCr(toCr(v.credit_by_document_age[k]))}`} style={{ width: `${(num(v.credit_by_document_age[k]) / (exposure(v) || 1)) * 100}%`, background: bucketColor(API_TO_BUCKET[k]) }} />
                      ))}
                      <i title={`Unclassified: ${fmtCr(toCr(v.credit_by_document_age.UNCLASSIFIED))}`} style={{ width: `${(num(v.credit_by_document_age.UNCLASSIFIED) / (exposure(v) || 1)) * 100}%`, background: UNCLASSIFIED_COLOR }} />
                    </span>
                  </span>
                  <span data-exact={v.credit_outstanding} className="num text-right text-[13px] font-semibold">{fmtCr(toCr(v.credit_outstanding))}</span>
                </li>
              ))}
            </ul>
            {page.total.vendors > rows.length && <div className="mt-2 text-[11px] text-muted-foreground">+ {(page.total.vendors - rows.length).toLocaleString("en-IN")} more vendors. Switch to Concentration for the full ranking.</div>}
          </div>
        );
      }}
    </LiveBoundary>
  );
}

/* ───────────── MOVEMENT: needs two snapshots ───────────── */
function MovementView() {
  const s = useLiveSummary();
  return (
    <div data-testid="movement-lens">
      <NotAvailable
        testId="movement-unavailable"
        title="Movement is not available yet"
        reason={`Movement needs two verified snapshots to compare. This is the first one${s.data ? ` (as of ${s.data.as_of_date})` : ""}. Nothing is estimated: month-on-month change, ageing migration and settled-versus-new appear once a second snapshot has been loaded and verified.`}
      />
    </div>
  );
}

/* ───────────── DEBITS & GAPS: facts as found, no accounting conclusion ───────────── */
function GapsView() {
  const s = useLiveSummary();
  const led = useLiveLedgers();
  const age = useLiveDocumentAge();
  const due = useLiveDueStatus();
  const { age: sel, select } = useRoomSelection();
  return (
    <div data-testid="abnormal-lens">
      <div className="border-b bg-[oklch(0.985_0.03_90)] px-4 py-2 text-[11.5px] text-[oklch(0.4_0.08_75)]" data-testid="abnormal-note">
        Diagnostic facts only. Debit balances in creditor ledgers are shown as found: they are not classified as vendor advances, and they are never netted into Credit Outstanding.
      </div>
      <LiveBoundary query={s} skeleton={<Skeleton className="m-4 h-[240px]" />}>
        {(sum) => {
          const un = age.data?.find((r) => r.bucket === "UNCLASSIFIED");
          const inv = due.data?.find((r) => r.state === "DUE_INVALID");
          const row = (id: string, label: string, desc: string, amount: string, detail: string, onClick?: () => void, active?: boolean) => {
            const inner = (
              <>
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-semibold text-foreground">{label}</span>
                  <span className="block truncate text-[11px] text-muted-foreground" title={desc}>{desc}</span>
                </span>
                <span className="num text-right text-[12px] text-muted-foreground">{detail}</span>
                <span data-exact={amount} className="num text-right text-[14px] font-semibold">{fmtCr(toCr(amount))}</span>
                {onClick ? <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" /> : <span />}
              </>
            );
            const cls = "grid w-full grid-cols-[minmax(0,2.6fr)_170px_120px_16px] items-center gap-x-3 border-t px-4 py-2 text-left";
            return onClick ? (
              <button key={id} data-testid={`gap-${id}`} aria-pressed={active} onClick={onClick} className={cn(cls, "press hover:bg-[oklch(0.97_0.012_265)]", active && "bg-[oklch(0.95_0.025_265)]")}>{inner}</button>
            ) : (
              <div key={id} data-testid={`gap-${id}`} className={cls}>{inner}</div>
            );
          };
          return (
            <div>
              {row("debit", "Debit balance in creditor ledgers", "Dr items in creditor ledgers; classification pending", sum.creditor_debit_balance, `${sum.debit_items.toLocaleString("en-IN")} items · ${sum.debit_vendors.toLocaleString("en-IN")} vendors`)}
              {led.data?.filter((l) => num(l.debit_balance) > 0).map((l) => row(`debit-${l.ledger_code}`, `   in ${l.ledger_name}`, `Ledger ${l.ledger_code}`, l.debit_balance, `${l.debit_items.toLocaleString("en-IN")} items · ${l.debit_vendors.toLocaleString("en-IN")} vendors`))}
              {row("due_unavailable", "Credit with no due date", "Due date absent in the source; not estimated", sum.due_unavailable_credit, `${sum.due_unavailable_items.toLocaleString("en-IN")} items`, () => select("due_unavailable"), sel === "due_unavailable")}
              {inv && inv.credit_items + inv.debit_items > 0 && row("due_invalid", "Invalid due date", "A due date exists but is invalid", inv.credit_outstanding, `${inv.credit_items} Cr · ${inv.debit_items} Dr items`, () => select("due_invalid"), sel === "due_invalid")}
              {un && un.credit_items + un.debit_items > 0 && row("unclassified", "No usable document date (credit)", `Held outside the Document Age buckets · debit ${fmtRupees(un.debit_balance)}`, un.credit_outstanding, `${un.credit_items} Cr · ${un.debit_items} Dr items`)}
            </div>
          );
        }}
      </LiveBoundary>
    </div>
  );
}

/** Four diagnostic lenses. The selected lens is URL state (`lens=`). */
export function LensWorkspace() {
  const { state, dispatch } = useCfo();
  const { age } = useRoomSelection();
  const lens = state.lens;
  return (
    <section aria-label="Diagnostic lenses" data-testid="lens-workspace" className="rounded-md border bg-card shadow-elegant">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b px-4 pt-3">
        <div>
          <div className="eyebrow">Diagnosis</div>
          <h2 className="text-[15px] font-semibold tracking-tight">{LENS_TABS.find((l) => l.id === lens)?.hint}</h2>
        </div>
        <div className="flex items-center gap-2 pb-2">
          {age !== "all" && <span className="rounded bg-[oklch(0.95_0.025_265)] px-2 py-0.5 text-[11.5px] font-semibold text-primary" data-testid="lens-filter-chip">Filtered: {AGE_FILTER_LABELS[age]}</span>}
        </div>
      </div>
      <div role="tablist" aria-label="Lens" className="flex gap-1 border-b px-4 pt-2">
        {LENS_TABS.map((l) => (
          <button
            key={l.id}
            role="tab"
            data-testid={`lens-${l.id}`}
            aria-selected={lens === l.id}
            onClick={() => dispatch({ type: "setLens", value: l.id })}
            className={cn("press -mb-px border-b-2 px-3 py-1.5 text-[12.5px] font-semibold", lens === l.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}
          >
            {l.label}
          </button>
        ))}
      </div>
      {lens === "age" && <AgeView />}
      {lens === "concentration" && <ConcentrationView />}
      {lens === "movement" && <MovementView />}
      {lens === "abnormal" && <GapsView />}
    </section>
  );
}
