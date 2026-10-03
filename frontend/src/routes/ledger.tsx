import { createFileRoute } from "@tanstack/react-router";
import { LedgerPage } from "@/components/cfo/DeepPages";

export const Route = createFileRoute("/ledger")({
  head: () => ({
    meta: [
      { title: "General Ledger · CityKart FP&A" },
      { name: "description", content: "General Ledger workspace for the CFO Operating System. Demo data." },
      { property: "og:title", content: "General Ledger · CityKart FP&A" },
      { property: "og:description", content: "General Ledger workspace. Demo data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: LedgerPage,
});
