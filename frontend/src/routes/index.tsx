import { createFileRoute } from "@tanstack/react-router";
import { CommandCenter } from "@/components/cfo/CommandCenter";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "CFO Command Center · CityKart FP&A" },
      { name: "description", content: "Financial pulse, what changed, cash and working capital, risk landscape and forecast trajectory." },
      { property: "og:title", content: "CFO Command Center · CityKart FP&A" },
      { property: "og:description", content: "Progressive financial investigation, demo data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: CommandCenter,
});
