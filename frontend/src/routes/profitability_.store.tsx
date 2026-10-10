import { createFileRoute, redirect } from "@tanstack/react-router";
import { StoreWorkspacePage } from "@/components/cfo/profitability/StoreWorkspacePage";

export const Route = createFileRoute("/profitability_/store")({
  // a drill-only workspace: without its context in the address there is nothing to show, so return to the page that owns the list
  beforeLoad: ({ search }) => {
    if (!(search as { drill?: string }).drill) throw redirect({ to: "/profitability" });
  },
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
