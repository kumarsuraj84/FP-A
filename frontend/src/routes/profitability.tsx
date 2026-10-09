import { createFileRoute } from "@tanstack/react-router";
import { PnlRoom } from "@/components/cfo/pnl/PnlRoom";

export const Route = createFileRoute("/profitability")({
  head: () => ({
    meta: [
      { title: "Profitability · CityKart FP&A" },
      { name: "description", content: "Store P&L actuals from verified data on the books basis: revenue from operations, Material Cost, Material Margin, Store Expenses, Store EBITDA and Corporate EBITDA, 4-Wall EBITDA by store, top and bottom stores, growth against 4-Wall EBITDA margin. AOP not available." },
      { property: "og:title", content: "Profitability · CityKart FP&A" },
      { property: "og:description", content: "Store profitability from verified data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: PnlRoom,
});
