import { createFileRoute, redirect } from "@tanstack/react-router";
import { LedgerPage } from "@/components/cfo/DeepPages";

export const Route = createFileRoute("/ledger")({
  // these workspaces exist only inside a drill (the context is in the address): without one there is nothing to show, so go home at once instead of rendering the Command Center under this address
  beforeLoad: ({ search }) => {
    if (!(search as { drill?: string }).drill) throw redirect({ to: "/" });
  },
  head: () => ({
    meta: [
      { title: "General Ledger · CityKart FP&A" },
      { name: "description", content: "General Ledger workspace for the CFO Operating System. Demo data." },
      { property: "og:title", content: "General Ledger · CityKart FP&A" },
      { property: "og:description", content: "General Ledger workspace. Demo data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: LedgerPage,
});
