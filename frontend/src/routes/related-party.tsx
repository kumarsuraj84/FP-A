import { createFileRoute } from "@tanstack/react-router";
import { RelatedPartyPage } from "@/components/cfo/related/RelatedPartyPage";

export const Route = createFileRoute("/related-party")({
  head: () => ({
    meta: [
      { title: "Related Party Transactions · CityKart FP&A" },
      { name: "description", content: "Intercompany creditors and loans, kept out of Creditors, Cash and the Command Center; eliminated on consolidation." },
      { property: "og:title", content: "Related Party Transactions · CityKart FP&A" },
      { property: "og:description", content: "Intercompany creditors and loans, kept out of Creditors, Cash and the Command Center." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: RelatedPartyPage,
});
