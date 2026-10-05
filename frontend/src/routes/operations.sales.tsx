import { createFileRoute } from "@tanstack/react-router";
import { SalesComparison } from "@/components/ops/SalesComparison";

export const Route = createFileRoute("/operations/sales")({
  head: () => ({
    meta: [
      { title: "Sales Comparison · CityKart Operations" },
      { name: "description", content: "Sales against a reference period by store, with the reference dates shown. Sample-data prototype." },
      { property: "og:title", content: "Sales Comparison · CityKart Operations" },
      { property: "og:description", content: "Sales comparison prototype on sample data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: SalesComparison,
});
