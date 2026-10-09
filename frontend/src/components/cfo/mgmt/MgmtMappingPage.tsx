import { useMemo, useState } from "react";
import { useMgmtMapping } from "@/api/mgmtLiveHooks";
import { DASH } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { MgmtFrame } from "./MgmtFrame";
import { cr2, toneOf } from "./mgmtFormat";

function MappingBody() {
  const map = useMgmtMapping();
  const [find, setFind] = useState("");
  const needle = find.trim().toLowerCase();
  const rows = useMemo(() => (map.data?.rows ?? []).filter((r) => !needle || [r.ledger, r.mgmt_group, r.major_group, r.category ?? ""].some((x) => x.toLowerCase().includes(needle))), [map.data, needle]);
  return (
    <LiveBoundary query={map} skeleton={<Skeleton className="m-4 h-[360px]" />}>
      {(d) => {
        const unmapped = d.exceptions.reduce((s, e) => s + e.amount_cr, 0);
        return (
          <>
            <div className="p-3">
              <Panel
                testId="mapping-exceptions"
                eyebrow={d.exceptions.length > 0 ? "Needs a decision" : "Clean"}
                title={`Unmapped and conflicting ledgers (${d.exceptions.length})`}
                right={d.exceptions.length > 0 ? <span data-testid="mapping-exceptions-total" data-exact={String(unmapped)} className={cn("num-mono text-[12px] font-semibold", toneOf(unmapped))}>{cr2(unmapped)} INR Cr</span> : undefined}
              >
                {d.exceptions.length === 0 ? (
                  <div data-testid="mapping-exceptions-empty" className="px-4 py-4 text-[12.5px] text-muted-foreground">Every ledger in the selected run has a management group.</div>
                ) : (
                  <table className="w-full text-[12.5px]" data-testid="mapping-exceptions-table">
                    <thead>
                      <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                        <th className="px-4 py-2 font-semibold">Ledger</th>
                        <th className="px-3 py-2 text-right font-semibold">INR Cr</th>
                        <th className="px-3 py-2 font-semibold">Why it is listed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.exceptions.map((e) => (
                        <tr key={e.ledger} className="border-b bg-[oklch(0.985_0.02_25)] last:border-0" data-testid={`exception-${e.ledger}`}>
                          <td className="px-4 py-1.5 font-medium">{e.ledger}</td>
                          <td className={cn("num-mono px-3 py-1.5 text-right", toneOf(e.amount_cr))}>{cr2(e.amount_cr)}</td>
                          <td className="px-3 py-1.5 text-muted-foreground">{e.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Panel>
            </div>
            <div className="px-3 pb-6">
              <Panel
                testId="mapping-panel"
                eyebrow="Versioned mapping"
                title={`Ledger map (${rows.length}${needle ? ` of ${d.rows.length}` : ""})`}
                right={<input data-testid="mapping-search" aria-label="Find a ledger" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Ledger or group" className="h-7 w-48 rounded border bg-card px-2 text-[12px]" />}
              >
                <div className="max-h-[65vh] overflow-auto">
                  <table className="w-full min-w-[720px] border-separate border-spacing-0 text-[12.5px]" data-testid="mapping-table">
                    <thead>
                      <tr className="text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                        {["Ledger", "Management group", "MIS line", "Category", "Source", "Note"].map((h, i) => (
                          <th key={h} className={cn("sticky top-0 z-20 border-b bg-card px-3 py-2 font-semibold", i === 0 && "left-0 z-30 border-r")}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={`${r.ledger}-${r.mgmt_group}`} className="hover:bg-muted/40">
                          <th scope="row" className="sticky left-0 z-10 whitespace-nowrap border-b border-r bg-card px-3 py-1.5 text-left font-normal">{r.ledger}</th>
                          <td className="border-b px-3 py-1.5">{r.mgmt_group}</td>
                          <td className="border-b px-3 py-1.5">{r.major_group}</td>
                          <td className="border-b px-3 py-1.5 text-muted-foreground">{r.category ?? DASH}</td>
                          <td className="border-b px-3 py-1.5 text-muted-foreground">{r.source}</td>
                          <td className="border-b px-3 py-1.5 text-muted-foreground">{r.note ?? ""}</td>
                        </tr>
                      ))}
                      {rows.length === 0 && <tr><td colSpan={6} data-testid="mapping-empty" className="px-4 py-6 text-center text-muted-foreground">No ledger matches.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </div>
          </>
        );
      }}
    </LiveBoundary>
  );
}

export function MgmtMappingPage() {
  return (
    <MgmtFrame active="mapping" entitySelector={false} subtitle="How ledgers roll up to the management groups and MIS lines, and the ledgers that have no group or more than one. Unmapped ledgers are the first thing to fix when the portal and the MIS disagree.">
      {() => <MappingBody />}
    </MgmtFrame>
  );
}
