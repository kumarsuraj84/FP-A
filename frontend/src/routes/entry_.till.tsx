import { createFileRoute } from "@tanstack/react-router";
import { TillDaysPage } from "@/components/cfo/entry/TillDaysPage";

export const Route = createFileRoute("/entry_/till")({
  head: () => ({
    meta: [
      { title: "Store till drill · CityKart FP&A" },
      { name: "description", content: "Store Till Cash by store and day, down to the vouchers." },
      { property: "og:title", content: "Store till drill · CityKart FP&A" },
      { property: "og:description", content: "Store Till Cash by store and day, down to the vouchers." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: TillDaysPage,
});
