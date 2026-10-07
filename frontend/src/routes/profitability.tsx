import { createFileRoute } from "@tanstack/react-router";
import { PnlRoom } from "@/components/cfo/pnl/PnlRoom";

export const Route = createFileRoute("/profitability")({
  head: () => ({
    meta: [
      { title: "Profitability · CityKart FP&A" },
      { name: "description", content: "Store P&L actuals from verified data: net sales ex-GST, COGS, gross margin, store opex and contribution by store, top and bottom stores, growth against contribution margin. Budget not available." },
      { property: "og:title", content: "Profitability · CityKart FP&A" },
      { property: "og:description", content: "Store profitability from verified data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: PnlRoom,
});
