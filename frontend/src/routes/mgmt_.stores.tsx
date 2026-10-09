import { createFileRoute } from "@tanstack/react-router";
import { validateMgmtSearch } from "@/components/cfo/mgmt/mgmtEntity";
import { MgmtStoresPage } from "@/components/cfo/mgmt/MgmtStoresPage";

export const Route = createFileRoute("/mgmt_/stores")({
  validateSearch: validateMgmtSearch,
  head: () => ({
    meta: [
      { title: "Management store league · CityKart FP&A" },
      { name: "description", content: "Revenue from operations, Gross Margin, Store Expenses, 4-Wall EBITDA and EBITDA after the apportioned DC and HO cost, by store." },
      { property: "og:title", content: "Management store league · CityKart FP&A" },
      { property: "og:description", content: "Revenue from operations, Gross Margin, Store Expenses, 4-Wall EBITDA and EBITDA after the apportioned DC and HO cost, by store." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: MgmtStoresPage,
});
