import { createFileRoute, redirect } from "@tanstack/react-router";
import { VoucherPage } from "@/components/cfo/DeepPages";

export const Route = createFileRoute("/voucher")({
  // these workspaces exist only inside a drill (the context is in the address): without one there is nothing to show, so go home at once instead of rendering the Command Center under this address
  beforeLoad: ({ search }) => {
    if (!(search as { drill?: string }).drill) throw redirect({ to: "/" });
  },
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
