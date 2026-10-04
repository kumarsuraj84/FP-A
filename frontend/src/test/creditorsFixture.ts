import { vi } from "vitest";

/**
 * A SYNTHETIC Creditors API for UI tests: three invented vendors, round numbers, no real data. It answers the same routes and
 * shapes as the real API (money as exact decimal text, `data_state` stated by the API, Finance routes gated).
 */
export const RUN = "run_test_001";
export const HEADER = {
  extraction_run_id: RUN,
  as_of_date: "2026-10-04",
  recon_state: "api_verified",
  publication_state: "unpublished",
  data_state: "verified_candidate",
  data_state_label: "Verified candidate (not published)",
  contract_version: "creditors-pilot-1.0",
  rules_version: "r1",
};

const AGE_KEYS = ["D0_30", "D31_60", "D61_90", "D91_180", "D181_365", "D365_PLUS", "UNCLASSIFIED"] as const;
const DUE_KEYS = ["NOT_YET_DUE", "PAST_DUE_OR_DUE_TODAY", "DUE_UNAVAILABLE", "DUE_INVALID"] as const;
const m = (n: number) => `${n}.0000`;

interface V { ref: string; name: string; age: number[]; due: number[]; debit: number; oldest: number }
// age: D0_30 … D365_PLUS (credit); due: NOT_YET, PAST_DUE, UNAVAILABLE, INVALID. Sum(age) == Sum(due) per vendor.
const VENDORS: V[] = [
  { ref: "Vaaaaaaaaaaaa", name: "Alpha Textiles (test)", age: [100e6, 100e6, 50e6, 150e6, 100e6, 50e6], due: [200e6, 200e6, 150e6, 0], debit: 50e6, oldest: 410 },
  { ref: "Vbbbbbbbbbbbb", name: "Beta Packaging (test)", age: [100e6, 50e6, 30e6, 70e6, 0, 0], due: [150e6, 70e6, 30e6, 0], debit: 0, oldest: 170 },
  { ref: "Vcccccccccccc", name: "Gamma Services (test)", age: [100e6, 50e6, 20e6, 30e6, 0, 0], due: [150e6, 30e6, 20e6, 0], debit: 0, oldest: 120 },
];
const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
const AGE_TOTAL = AGE_KEYS.slice(0, 6).map((_, i) => sum(VENDORS.map((v) => v.age[i])));
const DUE_TOTAL = DUE_KEYS.map((_, i) => sum(VENDORS.map((v) => v.due[i])));
const CREDIT = sum(AGE_TOTAL);

const vendorRow = (v: V, named: boolean, cohortCredit?: number) => ({
  vendor_ref: v.ref,
  ...(named ? { vendor_name: v.name, slid: "SL-1", sub_ledger_code: "SC-1", credit_days: 30 } : {}),
  party_class: "Trade",
  party_class_type: "Supplier",
  ledger_codes: ["1000000026"],
  items: 10,
  credit_items: 9,
  debit_items: v.debit ? 1 : 0,
  credit_outstanding: m(sum(v.age)),
  debit_balance: m(v.debit),
  signed_net: m(v.debit - sum(v.age)),
  past_due_credit: m(v.due[1]),
  due_unavailable_credit: m(v.due[2]),
  oldest_credit_age_days: v.oldest,
  share_of_credit: (sum(v.age) / CREDIT).toFixed(6),
  credit_by_document_age: Object.fromEntries(AGE_KEYS.map((k, i) => [k, m(i < 6 ? v.age[i] : 0)])),
  credit_by_due_status: Object.fromEntries(DUE_KEYS.map((k, i) => [k, m(v.due[i])])),
  ...(cohortCredit === undefined ? {} : { cohort_credit: m(cohortCredit) }),
});

const COHORT: Record<string, (v: V) => number> = {
  gt90: (v) => v.age[3] + v.age[4] + v.age[5],
  gt180: (v) => v.age[4] + v.age[5],
  past_due: (v) => v.due[1],
  not_yet_due: (v) => v.due[0],
  due_unavailable: (v) => v.due[2],
  due_invalid: (v) => v.due[3],
  D0_30: (v) => v.age[0],
  D31_60: (v) => v.age[1],
  D61_90: (v) => v.age[2],
  D91_180: (v) => v.age[3],
  D181_365: (v) => v.age[4],
  D365_PLUS: (v) => v.age[5],
};

export const FIXTURE = {
  credit: m(CREDIT),
  debit: m(50e6),
  net: m(50e6 - CREDIT),
  pastDue: m(DUE_TOTAL[1]),
  dueUnavailable: m(DUE_TOTAL[2]),
  over90: m(AGE_TOTAL[3] + AGE_TOTAL[4] + AGE_TOTAL[5]),
  over180: m(AGE_TOTAL[4] + AGE_TOTAL[5]),
  vendors: VENDORS,
};

const items = (v: V, named: boolean, drcr: string | null) => {
  const all = [
    { drcr: "Cr", pending: m(sum(v.age)), due_status: "PAST_DUE_OR_DUE_TODAY", bucket: "D181_365", age: 200, due_date: "2026-08-01" },
    ...(v.debit ? [{ drcr: "Dr", pending: m(v.debit), due_status: "DUE_UNAVAILABLE", bucket: "D0_30", age: 12, due_date: null }] : []),
  ].filter((i) => !drcr || i.drcr === drcr);
  return all.map((i, n) => ({
    item_ref: `${v.ref}-item-${n}-deadbeef`,
    ledger_code: "1000000026",
    ledger_name: "Sundry Creditors Apparels",
    drcr: i.drcr,
    amount: i.pending,
    adjusted: "0.0000",
    pending: i.drcr === "Cr" ? `-${i.pending}` : i.pending, // the mart stores Cr negative, Dr positive
    document_type: "PI",
    document_date: "2026-03-18",
    due_date: i.due_date,
    entry_date: "2026-03-18",
    document_age_days: i.age,
    document_age_bucket: i.bucket,
    overdue_days: i.due_status === "PAST_DUE_OR_DUE_TODAY" ? 64 : null,
    due_status: i.due_status,
    date_quality_status: "OK",
    classification_status: "CLASSIFIED",
    ...(named ? { document_code: "DOC1", document_no: `PI-${n + 1}`, document_initial: "PI", ref_no: "R1", ref_date: null } : {}),
  }));
};

export interface ApiOpts {
  /** Finance access available (names) — false answers the Finance routes with 401, as an unauthorised caller would see */
  named?: boolean;
  /** fail every request with this status */
  fail?: number;
  /** cash: no verified cash run exists / no creditors run to compose */
  noCash?: boolean;
  noCreditors?: boolean;
  state?: string;
}

/** Installs the stub on global fetch. Returns the list of requested URLs (for assertions). */
export function installCreditorsApi(opts: ApiOpts = {}) {
  const named = opts.named ?? true;
  const calls: string[] = [];
  const header = { ...HEADER, ...(opts.state ? { data_state: opts.state } : {}) };
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      calls.push(url.pathname + url.search);
      if (url.pathname.startsWith("/cash-api/")) return cashResponse(url, opts, json);
      if (!url.pathname.startsWith("/creditors-api/")) return json({}, 404);
      if (opts.fail) return json({ detail: "boom" }, opts.fail);
      const path = url.pathname.slice("/creditors-api/".length);
      const finance = path.includes("/finance/");
      if (finance && !named) return json({ detail: "Finance authorization required" }, 401);
      const p = path.replace("/finance/", "/");
      if (p === "current") return json(header);
      let mm = p.match(/^runs\/([^/]+)\/(.*)$/);
      if (!mm) return json({}, 404);
      if (mm[1] !== RUN) return json({ detail: "that run does not exist or has not been verified" }, 404);
      const rest = mm[2];
      if (rest === "summary")
        return json({
          ...header,
          item_rows: 45,
          vendors: 3,
          credit_items: 40,
          debit_items: 5,
          credit_outstanding: FIXTURE.credit,
          creditor_debit_balance: FIXTURE.debit,
          signed_net: FIXTURE.net,
          past_due_credit: FIXTURE.pastDue,
          past_due_items: 12,
          due_unavailable_credit: FIXTURE.dueUnavailable,
          due_unavailable_items: 8,
          over_90_credit: FIXTURE.over90,
          over_90_items: 15,
          over_180_credit: FIXTURE.over180,
          over_180_items: 6,
          credit_vendors: 3,
          debit_vendors: 1,
          credit_concentration: { top_1: "0.4500", top_5: "1.0000", top_10: "1.0000", top_20: "1.0000" },
        });
      if (rest === "document-age") {
        const names = ["0–30", "31–60", "61–90", "91–180", "181–365", ">365"];
        return json({
          ...header,
          buckets: [
            ...AGE_TOTAL.map((c, i) => ({ bucket: AGE_KEYS[i], label: names[i], credit_items: 5, debit_items: i === 0 ? 1 : 0, credit_outstanding: m(c), debit_balance: m(i === 0 ? 50e6 : 0), signed_net: m((i === 0 ? 50e6 : 0) - c) })),
            { bucket: "UNCLASSIFIED", label: "Unclassified", credit_items: 1, debit_items: 0, credit_outstanding: "1000.0000", debit_balance: "0.0000", signed_net: "-1000.0000", reasons: [{ reason: "MISSING", credit_items: 1, debit_items: 0, credit_outstanding: "1000.0000", debit_balance: "0.0000" }] },
          ],
        });
      }
      if (rest === "due-status") {
        const labels = ["Not yet due", "Past due / due today", "Due date unavailable", "Invalid due date"];
        return json({ ...header, states: DUE_KEYS.map((k, i) => ({ state: k, label: labels[i], credit_items: i === 3 ? 0 : 10, debit_items: i === 2 ? 1 : 0, credit_outstanding: m(DUE_TOTAL[i]), debit_balance: m(i === 2 ? 50e6 : 0), signed_net: m(0) })) });
      }
      if (rest === "ledgers")
        return json({
          ...header,
          ledgers: [
            { ledger_code: "1000000026", ledger_name: "Sundry Creditors Apparels", credit_items: 30, debit_items: 4, credit_outstanding: m(700e6), debit_balance: m(50e6), signed_net: m(-650e6), vendors: 3, credit_vendors: 3, debit_vendors: 1, past_due_credit: m(200e6), due_unavailable_credit: m(100e6) },
            { ledger_code: "1000000024", ledger_name: "Sundry Creditors for Expenses", credit_items: 10, debit_items: 1, credit_outstanding: m(300e6), debit_balance: m(0), signed_net: m(-300e6), vendors: 2, credit_vendors: 2, debit_vendors: 0, past_due_credit: m(100e6), due_unavailable_credit: m(100e6) },
          ],
        });
      if (rest === "vendors") {
        const cohort = url.searchParams.get("cohort");
        const qtxt = url.searchParams.get("q")?.toLowerCase();
        const limit = Number(url.searchParams.get("limit") ?? 100);
        let vs = [...VENDORS];
        if (qtxt) vs = vs.filter((v) => v.name.toLowerCase().includes(qtxt));
        const rows = (cohort ? vs.filter((v) => COHORT[cohort](v) > 0).sort((a, b) => COHORT[cohort](b) - COHORT[cohort](a)) : vs.sort((a, b) => sum(b.age) - sum(a.age))).slice(0, limit);
        return json({
          ...header,
          total: { vendors: rows.length, credit_outstanding: FIXTURE.credit, debit_balance: FIXTURE.debit, signed_net: FIXTURE.net, ...(cohort ? { cohort_credit: m(sum(rows.map(COHORT[cohort]))) } : {}) },
          returned: rows.length,
          limit,
          offset: 0,
          vendors: rows.map((v) => vendorRow(v, finance, cohort ? COHORT[cohort](v) : undefined)),
        });
      }
      mm = rest.match(/^vendors\/([^/]+)(\/items)?$/);
      if (mm) {
        const v = VENDORS.find((x) => x.ref === mm![1]);
        if (!v) return json({ detail: "unknown vendor" }, 404);
        if (mm[2]) {
          const its = items(v, finance, url.searchParams.get("drcr"));
          return json({ ...header, vendor_ref: v.ref, total_items: its.length, returned: its.length, limit: 500, offset: 0, items: its });
        }
        return json({ ...header, vendor: vendorRow(v, finance) });
      }
      return json({}, 404);
    }),
  );
  return calls;
}

/* ───────────── a synthetic Cash API (invented stores and ledgers, round numbers) ───────────── */
export const CASH_RUN = "run_test_cash_001";
const STORES = Array.from({ length: 24 }, (_, i) => ({ site_code: String(100 + i), store_name: `Test Store ${String(i + 1).padStart(2, "0")}`, cumulative_balance: `${(24 - i) * 10000}.0000`, mtd_debit: "5000.0000", mtd_credit: "4500.0000", fytd_debit: "30000.0000", fytd_credit: "29000.0000", last_activity_date: "2026-10-03" }));
const TILL_TOTAL = STORES.reduce((a, s) => a + Number(s.cumulative_balance), 0);
const LEDGER = (code: string, name: string, opening: number, posted: number, unposted: number, nature = "Bank") => ({
  ledger_code: code, ledger_name: name, gl_type: "Asset", nature, extinct: "No", has_movement: true, opening_balance: `${opening}.0000`, posted_dr: "0.0000", posted_cr: "0.0000", posted_closing: `${posted}.0000`,
  unposted_dr: "0.0000", unposted_cr: "0.0000", unposted_movement: `${unposted}.0000`, including_unposted: `${posted + unposted}.0000`, future_net: "0.0000", last_posted_date: "2026-09-30", last_entry_date: "2026-10-02",
  register_report_date: "2026-10-04", sites: 3,
});
const BANK = [LEDGER("1", "TEST BANK ALPHA", 20000000, -830000000, 780000000), LEDGER("2", "TEST BANK BETA", 9900000, 7000000, -2800000), LEDGER("3", "TEST CASH IN HAND", 100000, 190000, -20000, "Cash")];
const BSUM = (k: "opening_balance" | "posted_closing" | "unposted_movement" | "including_unposted") => BANK.reduce((a, l) => a + Number(l[k]), 0);

function cashResponse(url: URL, opts: ApiOpts, json: (b: unknown, s?: number) => Response): Response {
  if (opts.fail) return json({ detail: "boom" }, opts.fail);
  const path = url.pathname.slice("/cash-api/".length);
  const state = opts.state ?? "verified_candidate";
  const header = { run_id: CASH_RUN, as_of_date: "2026-10-04", till_balance_date: "2026-10-03", recon_state: "api_verified", publication_state: state === "live" ? "live" : "unpublished", data_state: state, data_state_label: state, contract_version: "cash-wc-1.0", source_updated_at: "2026-10-04T10:00:00Z" };
  if (path === "current") return opts.noCash ? json({ detail: "none" }, 404) : json(header);
  if (path === `runs/${CASH_RUN}/summary`)
    return json({
      ...header,
      till: { label: "Store Till Cash", note: "excludes bank balances", stores: STORES.length, store_till_cash: `${TILL_TOTAL}.0000`, mtd_debit: "120000.0000", mtd_credit: "108000.0000", fytd_debit: "720000.0000", fytd_credit: "696000.0000", stores_negative: 0, stores_with_cash: STORES.length, last_activity_date: "2026-10-03", largest_store: { store_name: STORES[0].store_name, site_code: STORES[0].site_code, cumulative_balance: STORES[0].cumulative_balance } },
      bank_review: {
        status: "PROVISIONAL · NOT BANK-RECONCILED", source: "site_register", register_report_date: "2026-10-04", last_posted_date: "2026-09-30",
        totals: { opening_balance: `${BSUM("opening_balance")}.0000`, posted_closing: `${BSUM("posted_closing")}.0000`, unposted_movement: `${BSUM("unposted_movement")}.0000`, including_unposted: `${BSUM("including_unposted")}.0000` },
        ledgers_total: 5, ledgers_with_movement: 3, ledgers_without_movement: 2,
        driver: { ledger_code: "1", ledger_name: "TEST BANK ALPHA", posted_closing: BANK[0].posted_closing, including_unposted: BANK[0].including_unposted },
        ledgers: [...BANK].sort((a, b) => Number(a.posted_closing) - Number(b.posted_closing)),
        cross_check: { gl_register_posted_closing: `${BSUM("posted_closing")}.0000`, gl_register_including_unposted: "-100000.0000", gl_register_report_date: "2026-10-03", posted_agrees_with_gl_register: true },
        opening_ties_to_prior_year_closing: { ledgers_checked: 5, ledgers_not_tying: 0 },
      },
      creditors: opts.noCreditors ? { available: false, reason: "No verified creditors run is available." } : { available: true, creditors_run_id: RUN, as_of_date: "2026-10-04", data_state: "verified_candidate", credit_outstanding: FIXTURE.credit, creditor_debit_balance: FIXTURE.debit, signed_net: FIXTURE.net, past_due_credit: FIXTURE.pastDue, not_yet_due_credit: "500000000.0000", due_unavailable_credit: FIXTURE.dueUnavailable, credit_items: 40, credit_vendors: 3 },
      unavailable: ["bank_reconciled_cash", "consolidated_cash", "cash_forecast", "inventory", "receivables", "vendor_advances", "payroll", "statutory", "capex"].map((id) => ({ id, label: id.replaceAll("_", " "), reason: id === "cash_forecast" ? "No forecast source exists. A projection is not shown, and none is estimated." : `no source for ${id}` })),
    });
  if (path === `runs/${CASH_RUN}/store-till`) {
    const limit = Number(url.searchParams.get("limit") ?? 100);
    const stores = STORES.slice(0, limit);
    return json({ ...header, returned: stores.length, limit, offset: 0, stores });
  }
  return json({ detail: "not found" }, 404);
}
