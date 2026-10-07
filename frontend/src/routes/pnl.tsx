import { createFileRoute } from "@tanstack/react-router";
import { PnlRoom } from "@/components/cfo/pnl/PnlRoom";

export const Route = createFileRoute("/pnl")({
  head: () => ({
    meta: [
      { title: "Store P&L · CityKart FP&A" },
      { name: "description", content: "Store P&L actuals from verified data: net sales ex-GST, COGS, gross margin, store opex and contribution by store, with top and bottom stores and trend. Budget not available." },
      { property: "og:title", content: "Store P&L · CityKart FP&A" },
      { property: "og:description", content: "Store P&L actuals from verified data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: PnlRoom,
});
