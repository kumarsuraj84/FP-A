import { createFileRoute } from "@tanstack/react-router";
import { CreditorsRoom } from "@/components/cfo/creditors/CreditorsRoom";

export const Route = createFileRoute("/creditors")({
  head: () => ({
    meta: [
      { title: "Creditors Control Room · CityKart FP&A" },
      { name: "description", content: "How much we owe, how old it is, what is moving into risk, and which vendors need attention. Demo data." },
      { property: "og:title", content: "Creditors Control Room · CityKart FP&A" },
      { property: "og:description", content: "Creditor exposure, ageing migration and vendor investigation. Demo data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: CreditorsRoom,
});
