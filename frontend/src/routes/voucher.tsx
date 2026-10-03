import { createFileRoute } from "@tanstack/react-router";
import { VoucherPage } from "@/components/cfo/DeepPages";

export const Route = createFileRoute("/voucher")({
  head: () => ({
    meta: [
      { title: "Voucher Evidence · CityKart FP&A" },
      { name: "description", content: "Voucher Evidence workspace for the CFO Operating System. Demo data." },
      { property: "og:title", content: "Voucher Evidence · CityKart FP&A" },
      { property: "og:description", content: "Voucher Evidence workspace. Demo data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: VoucherPage,
});
