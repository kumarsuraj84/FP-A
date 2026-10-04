import { createFileRoute } from "@tanstack/react-router";
import { StoreWorkspacePage } from "@/components/cfo/profitability/StoreWorkspacePage";

export const Route = createFileRoute("/profitability_/store")({
  head: () => ({
    meta: [
      { title: "Store Workspace · CityKart FP&A" },
      { name: "description", content: "Store P&L bridge, trajectory, expense pressure and network comparison. Demo data." },
      { property: "og:title", content: "Store Workspace · CityKart FP&A" },
      { property: "og:description", content: "Store workspace. Demo data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: StoreWorkspacePage,
});
