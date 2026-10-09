import { createFileRoute } from "@tanstack/react-router";
import { LedgerEntriesPage } from "@/components/cfo/entry/LedgerEntriesPage";

export const Route = createFileRoute("/entry_/list")({
  head: () => ({
    meta: [
      { title: "Vouchers behind a ledger · CityKart FP&A" },
      { name: "description", content: "The vouchers behind one ledger at one store for a period or a day, from the gold voucher register." },
      { property: "og:title", content: "Vouchers behind a ledger · CityKart FP&A" },
      { property: "og:description", content: "The vouchers behind one ledger at one store for a period or a day, from the gold voucher register." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: LedgerEntriesPage,
});
