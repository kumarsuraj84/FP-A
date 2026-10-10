import { createFileRoute } from "@tanstack/react-router";
import { ClosePage } from "@/components/cfo/control/ClosePage";

export const Route = createFileRoute("/control/close")({
  head: () => ({ meta: [{ title: "Month-end close · CityKart FP&A" }, { name: "description", content: "Month-end close readiness: blockers, checklist, sign-offs and period actions. Sign-in required." }] }),
  component: ClosePage,
});
