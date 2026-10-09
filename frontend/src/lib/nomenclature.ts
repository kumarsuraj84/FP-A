/**
 * The finance MIS vocabulary (source: Citykart MIS Format workbook). One place, so every page says the same thing.
 * docs/NOMENCLATURE.md is the glossary (old portal term -> MIS term, definition, source line); keep both in step.
 */
export const T = {
  revenue: "Revenue from operations",
  otherOperatingIncome: "Other operating income",
  totalIncome: "Total income",
  materialCost: "Material Cost",
  materialMargin: "Material Margin",
  /** at store level the same line is Gross Margin (finance abbreviates it RGM; the abbreviation is not used in the portal) */
  grossMargin: "Gross Margin",
  storeExpenses: "Store Expenses",
  storeEbitda: "Store EBITDA",
  fourWall: "4-Wall EBITDA",
  freight: "Freight Forwarding",
  dcCost: "DC cost",
  hoCost: "HO cost",
  corporateCost: "Total Corporate Cost",
  corporateEbitda: "Corporate EBITDA",
  ly: "LY",
  yoy: "Y-o-Y Growth",
  sssg: "SSSG",
  aop: "AOP",
  sameStore: "Same Store / LFL 120",
  nonLfl: "Non-LFL",
  nsoTy: "NSO TY",
  closed: "Closed",
} as const;

/** Shown wherever the Profitability figures appear: they are the books, not the management P&L. */
export const BOOKS_BASIS_NOTE = "Books basis, before management adjustments; see Management P&L.";
export const NO_AOP = "AOP is not available for FY26-27 (the FY25-26 plan ended in March 2026). It is shown blank.";

/** MIS display name of a finance group code ("02-Employee Cost" -> "Employee Cost"). The raw code belongs in a tooltip. */
export const GROUP_NAME: Record<string, string> = {
  "01-Net Sales": "Revenue from operations",
  "02-Other Income": "Other operating income",
  "24-Interest Income": "Interest income",
  "02-COGS(Product)": "Material Cost (product)",
  "02-COGS(Others)": "Material Cost (purchase discounts and other)",
  "02-COGS(Correction)": "Material Cost (correction)",
  "01-Rent": "Rent",
  "02-Employee Cost": "Employee Cost",
  "03-Power and Fuel Expenses": "Power and Fuel",
  "05-Director remunaration": "Director remuneration",
  "07-Advertisement And Sales Promotion": "Advertisement",
  "08-Freight Outward": "Freight Forwarding",
  "09-Insurance": "Insurance",
  "10-Travelling & Conveyance Expenses": "Travel and Conveyance",
  "11-Communication": "Communication",
  "12-Repairs and Maintenance-Others": "Repairs and Maintenance",
  "13-Packing Materials And Expenses": "Packing",
  "14-Legal and Professional Expenses": "Legal and Professional",
  "16-Miscellaneous Expenses": "Miscellaneous",
  "17-Bank Charges": "Bank Charges",
  "20-Printing & Stationery": "Printing and Stationery",
  "21-Finance Cost": "Finance cost",
};

export function groupName(code: string | null | undefined): string {
  if (!code) return "";
  return GROUP_NAME[code] ?? code.replace(/^\d+-/, "");
}

/** The MIS line a finance group rolls up to (Other expenses holds insurance, travel, communication, repairs, packing, legal, miscellaneous, bank charges, printing). */
export const OTHER_EXPENSE_GROUPS = new Set([
  "09-Insurance", "10-Travelling & Conveyance Expenses", "11-Communication", "12-Repairs and Maintenance-Others", "13-Packing Materials And Expenses",
  "14-Legal and Professional Expenses", "16-Miscellaneous Expenses", "17-Bank Charges", "20-Printing & Stationery", "05-Director remunaration",
]);

/** Store vintage as the site master holds it (OLD / NEW) in the finance cohort wording. The finance LFL tag itself is not in the sources, so this is the nearest the data supports. */
export function vintageLabel(v: string | null | undefined): string {
  if (!v || v === "-") return "Unassigned";
  const u = v.toUpperCase();
  if (u.startsWith("OLD") || u.startsWith("SAME")) return T.sameStore;
  if (u.startsWith("NEW")) return T.nonLfl;
  return v;
}
