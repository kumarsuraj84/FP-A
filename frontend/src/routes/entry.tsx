import { createFileRoute } from "@tanstack/react-router";
import { EntryPage } from "@/components/cfo/entry/EntryPage";

export const Route = createFileRoute("/entry")({
  head: () => ({
    meta: [
      { title: "Voucher · CityKart FP&A" },
      { name: "description", content: "A voucher (accounting entry) with all its lines, balance check and source evidence, from the gold voucher register." },
      { property: "og:title", content: "Voucher · CityKart FP&A" },
      { property: "og:description", content: "A voucher (accounting entry) with all its lines, balance check and source evidence, from the gold voucher register." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: EntryPage,
});
