import { createFileRoute } from "@tanstack/react-router";
import { validateMgmtSearch } from "@/components/cfo/mgmt/mgmtEntity";
import { MgmtPnlPage } from "@/components/cfo/mgmt/MgmtPnlPage";

export const Route = createFileRoute("/mgmt")({
  validateSearch: validateMgmtSearch,
  head: () => ({
    meta: [
      { title: "Management P&L · CityKart FP&A" },
      { name: "description", content: "The finance MIS view of the P&L: revenue, store lines, store EBITDA, DC and HO cost and corporate EBITDA, each as book, management adjustment and total, in INR Cr." },
      { property: "og:title", content: "Management P&L · CityKart FP&A" },
      { property: "og:description", content: "The finance MIS view of the P&L: revenue, store lines, store EBITDA, DC and HO cost and corporate EBITDA, each as book, management adjustment and total, in INR Cr." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: MgmtPnlPage,
});
