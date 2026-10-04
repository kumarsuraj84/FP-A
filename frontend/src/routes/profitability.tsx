import { createFileRoute } from "@tanstack/react-router";
import { ProfitabilityRoom } from "@/components/cfo/profitability/ProfitabilityRoom";

export const Route = createFileRoute("/profitability")({
  head: () => ({
    meta: [
      { title: "Store Profitability · CityKart FP&A" },
      { name: "description", content: "Which stores earn their place in the network: growth against contribution margin. Demo data." },
      { property: "og:title", content: "Store Profitability · CityKart FP&A" },
      { property: "og:description", content: "Store profitability portfolio. Demo data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: ProfitabilityRoom,
});
