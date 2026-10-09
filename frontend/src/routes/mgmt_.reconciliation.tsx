import { createFileRoute } from "@tanstack/react-router";
import { validateMgmtSearch } from "@/components/cfo/mgmt/mgmtEntity";
import { MgmtReconPage } from "@/components/cfo/mgmt/MgmtReconPage";

export const Route = createFileRoute("/mgmt_/reconciliation")({
  validateSearch: validateMgmtSearch,
  head: () => ({
    meta: [
      { title: "Management P&L reconciliation · CityKart FP&A" },
      { name: "description", content: "The portal's management P&L against the published finance MIS by line and month, with the bridge between them." },
      { property: "og:title", content: "Management P&L reconciliation · CityKart FP&A" },
      { property: "og:description", content: "The portal's management P&L against the published finance MIS by line and month, with the bridge between them." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: MgmtReconPage,
});
