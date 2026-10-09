import { createFileRoute } from "@tanstack/react-router";
import { MgmtMappingPage } from "@/components/cfo/mgmt/MgmtMappingPage";

export const Route = createFileRoute("/mgmt_/mapping")({
  head: () => ({
    meta: [
      { title: "Management ledger mapping · CityKart FP&A" },
      { name: "description", content: "How ledgers roll up to management groups and MIS lines, and the ledgers that are unmapped or conflicting." },
      { property: "og:title", content: "Management ledger mapping · CityKart FP&A" },
      { property: "og:description", content: "How ledgers roll up to management groups and MIS lines, and the ledgers that are unmapped or conflicting." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: MgmtMappingPage,
});
