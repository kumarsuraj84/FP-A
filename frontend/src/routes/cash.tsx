import { createFileRoute } from "@tanstack/react-router";
import { CashRoom } from "@/components/cfo/cash/CashRoom";

export const Route = createFileRoute("/cash")({
  head: () => ({
    meta: [
      { title: "Cash & Working Capital · CityKart FP&A" },
      { name: "description", content: "Cash today and over 7, 15 and 30 days, obligations approaching, and what working capital is absorbing or releasing. Demo data." },
      { property: "og:title", content: "Cash & Working Capital · CityKart FP&A" },
      { property: "og:description", content: "Cash and working capital control. Demo data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: CashRoom,
});
