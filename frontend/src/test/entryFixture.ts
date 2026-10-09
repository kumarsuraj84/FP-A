import { vi } from "vitest";

/**
 * A SYNTHETIC Entry API for the UI tests: invented vouchers and round numbers, nothing from the database. It answers the same routes and shapes as the
 * real API (money as exact decimal text; the data state is stated by the API; Finance routes are gated and fall back to the masked ones).
 * `installEntryApi` wraps whatever `fetch` is already stubbed, so it composes with the creditors / pnl fixtures.
 */
export const ENTRY_RUN = "ENTRY-TEST";
export const CRED_RUN = "GOLD-TEST";
export const CASH_RUN = "CASH-TEST";
export const RUN_HEADER = {
  entry_run_id: ENTRY_RUN,
  register_report_date: "2026-10-09",
  till_balance_date: "2026-10-09",
  cash_run_id: CASH_RUN,
  creditors_run_id: CRED_RUN,
  coverage_from: "2025-04-01",
  recon_state: "verified",
  publication_state: "live",
  data_state: "live",
  data_state_label: "Live",
  source_updated_at: "2026-10-09 16:26:49+05:30",
};

const line = (n: number, code: string, name: string, nature: string, dr: string, cr: string, ref: string | null = null) => ({
  line_no: n, ledger_code: code, ledger_name: name, ledger_nature: nature, sub_ledger_ref: ref, debit: dr, credit: cr, release_status: "Unposted", cube_name: null,
});

/** E1 balances; E2 is missing its creditor leg (the gold gap): Dr 1,000 against Cr 0. */
export const E1 = { ref: "9000000001", lines: [
  line(1, "1000000008", "Cash Drawer", "Asset", "26548", "0"),
  line(2, "1114926171", "Mob Wallet Receivable", "Asset", "41796", "0", "Vabc123def456"),
  line(3, "1000000037", "Sales - POS", "Income", "0", "64031.59"),
  line(4, "267", "CGST Output A/C", "Liability", "0", "2156.20"),
  line(5, "268", "SGST Output A/C", "Liability", "0", "2156.21"),
] };
export const E2 = { ref: "9000000002", lines: [
  line(1, "1000000053", "Salaries", "Expense", "1000", "0"),
  line(2, "1000000054", "Staff Welfare", "Expense", "0", "0"),
] };

const entryBody = (ref: string, finance: boolean) => {
  const e = ref === E1.ref ? E1 : E2;
  const balanced = ref === E1.ref;
  const lines = e.lines.map((l) => (finance ? { ...l, text: { sub_ledger_code: l.sub_ledger_ref ? "SC-77" : null, narration: l.line_no === 1 ? "Auto created till entry" : null, reference_no: "POS Consolidated", reference_date: null, cheque_no: null, cheque_date: null, counter_ledgers: null, prepared_by: null, prepared_on: null, modified_by: null, modified_on: null, released_by: null, released_on: null } } : l));
  return {
    ...RUN_HEADER,
    entry: {
      entry_ref: ref, site_code: "68", entry_type_short: balanced ? "CSM" : "JDJ", entry_type_long: balanced ? "Retail Sale" : "Journal", entry_date: "2026-10-05", release_status: balanced ? "Unposted" : "Posted",
      line_count: e.lines.length, total_dr: balanced ? "68344" : "1000", total_cr: balanced ? "68344.00" : "0", selections: balanced ? ["till", "creditors"] : [], lines, balanced,
      linked_bills: balanced ? [{ item_ref: "555", link_status: "STRONG", coverage: "CURRENT_FY" }] : [], attachment: { available: false, message: "No verified attachment source available" },
      ...(finance ? { identity: { site_code: "68", entry_type_short: balanced ? "CSM" : "JDJ", entry_no: balanced ? "47675" : "JV-12", created_by_site: "Test Store 68" } } : {}),
    },
  };
};

const lineDetail = (ref: string, finance: boolean) => {
  const e = ref === E1.ref ? E1 : E2;
  return {
    ...RUN_HEADER, entry_ref: ref,
    lines: e.lines.map((l) => ({ line_no: l.line_no, fin_group: l.ledger_nature === "Expense" ? "02-Employee Cost" : "UNMAPPED", fin_major_group: null, site_code: 298, store_name: "JGR", site_kind: "STORE", profit_effect: "-1", ...(finance ? { vendor_name: l.sub_ledger_ref ? "Paytm (test)" : null, vendor_class: l.sub_ledger_ref ? "Credit Card" : null } : {}) })),
  };
};

/** 230 vouchers on ledger 77 at site 10; the list is paged by `limit` / `offset`. */
const ALL_ROWS = Array.from({ length: 230 }, (_, i) => ({
  entry_ref: String(9100000000 + i), entry_date: "2026-09-15", entry_type_short: "JDJ", entry_type_long: "Journal", release_status: "Posted", lines: 1, debit: "1000", credit: "0", net: "-1000",
}));

export interface EntryOpts {
  /** Finance access available (narration, party names). false answers the Finance routes with 401, as an unauthorised caller would see */
  named?: boolean;
  /** fail every Entry API request with this status */
  fail?: number;
  /** make the till days not add up to the store figure */
  tillBroken?: boolean;
}

export function installEntryApi(opts: EntryOpts = {}) {
  const named = opts.named ?? true;
  const calls: string[] = [];
  const next = globalThis.fetch;
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      if (!url.pathname.startsWith("/entry-api/")) return next ? next(input, init) : json({}, 404);
      calls.push(url.pathname + url.search);
      if (opts.fail) return json({ detail: "boom" }, opts.fail);
      const raw = url.pathname.slice("/entry-api/".length);
      const finance = raw.includes("/finance/");
      if (finance && !named) return json({ detail: "Finance authorization required" }, 401);
      const path = raw.replace("/finance/", "/");
      if (path === "current") return json(RUN_HEADER);
      const m = path.match(/^runs\/([^/]+)\/(.*)$/);
      if (!m) return json({}, 404);
      if (m[1] !== ENTRY_RUN) return json({ detail: "that entry run does not exist or has not been verified" }, 404);
      const rest = m[2];
      const q = url.searchParams;
      let g: RegExpMatchArray | null;
      if ((g = rest.match(/^entry\/([^/]+)\/line-detail$/))) return [E1.ref, E2.ref].includes(g[1]) ? json({ ...lineDetail(g[1], finance), named: finance }) : json({ detail: "unknown entry" }, 404);
      if ((g = rest.match(/^entry\/([^/]+)$/))) return [E1.ref, E2.ref].includes(g[1]) ? json(entryBody(g[1], finance)) : json({ detail: "unknown entry" }, 404);
      if (rest === "ledger-entries") {
        const limit = Number(q.get("limit") ?? 100);
        const offset = Number(q.get("offset") ?? 0);
        const day = q.get("from_date") && q.get("from_date") === q.get("to_date");
        const rows = day ? ALL_ROWS.slice(0, 2) : ALL_ROWS;
        const shown = rows.slice(offset, offset + limit).map((r) => (finance ? { ...r, narration: "Salary Sep (test)" } : r));
        const total = rows.length;
        return json({
          ...RUN_HEADER,
          scope: { site: q.get("site") ? Number(q.get("site")) : null, glcode: q.get("glcode") ? Number(q.get("glcode")) : null, ledger_name: "Salary", from_month: q.get("from_month"), to_month: q.get("to_month"), from_date: q.get("from_date"), to_date: q.get("to_date"), basis: q.get("basis") ?? "all" },
          parent: { net: String(-1000 * total), debit: String(1000 * total), credit: "0", lines: total }, children_sum: { net: String(-1000 * shown.length) },
          reconciles: offset === 0 && shown.length === total ? true : null,
          total: { entries: total, lines: total, debit: String(1000 * total), credit: "0", net: String(-1000 * total) },
          returned: shown.length, limit, offset, named: finance, entries: shown,
        });
      }
      if ((g = rest.match(/^creditors\/items\/([^/]+)\/link$/))) {
        const base = { item_ref: g[1], creditors_run_id: CRED_RUN, ledger_code: "1000000026", bill_amount: "-5000", key_used: "DOCUMENT_CODE", entry_net_amount: null, amount_agrees: null };
        const link =
          g[1] === "555" ? { ...base, link_status: "STRONG", not_linked_reason: null, matched_entries: 1, entry_ref: E1.ref, coverage: "CURRENT_FY" }
          : g[1] === "777" ? { ...base, link_status: "NOT_LINKED", not_linked_reason: "REGISTER_COVERAGE_UNAVAILABLE", matched_entries: 0, entry_ref: null, coverage: "BEFORE_COVERAGE" }
          : { ...base, link_status: "NOT_LINKED", not_linked_reason: "NO_MATCH", matched_entries: 0, entry_ref: null, coverage: "CURRENT_FY" };
        return json({ ...RUN_HEADER, link, attachment: { available: false, message: "No verified attachment source available" } });
      }
      if (rest === "till/stores")
        return json({
          ...RUN_HEADER, label: "Store Till Cash", note: "excludes bank balances", balance_date: "2026-10-09", parent: { store_till_cash: "30000", stores: 2 }, children_sum: { store_till_cash: "30000", stores: 2 }, reconciles: true,
          stores: [{ site_code: 439, balance: "20000", total_debit: "50000", total_credit: "30000", active_days: 5 }, { site_code: 447, balance: "10000", total_debit: "10000", total_credit: "0", active_days: 1 }],
        });
      if ((g = rest.match(/^till\/stores\/([^/]+)\/days$/)))
        return json({
          ...RUN_HEADER, site_code: g[1], balance_date: "2026-10-09", parent: { balance: "20000" }, children_sum: { balance: opts.tillBroken ? "19000" : "20000" }, reconciles: !opts.tillBroken, deepest_level: "till_day", note: "The till drill ends at the store-day: individual POS cash lines are not part of the entry layer.",
          days: [{ day: "2026-03-31", debit: "5000", credit: "0", cumulative_balance: "5000" }, { day: "2026-10-07", debit: "15000", credit: "0", cumulative_balance: "20000" }],
        });
      return json({}, 404);
    }),
  );
  return calls;
}
