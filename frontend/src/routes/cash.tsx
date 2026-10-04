import { createFileRoute } from "@tanstack/react-router";
import { CashRoom } from "@/components/cfo/cash/CashRoom";

export const Route = createFileRoute("/cash")({
  head: () => ({
    meta: [
      { title: "Liquidity & Working Capital · CityKart FP&A" },
      { name: "description", content: "Store till cash, creditor obligations and a provisional bank ledger-book review, from verified data. No forecast." },
      { property: "og:title", content: "Liquidity & Working Capital · CityKart FP&A" },
      { property: "og:description", content: "Store till cash, creditor obligations and a provisional bank review." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: CashRoom,
});
