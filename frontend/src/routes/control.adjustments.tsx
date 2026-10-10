import { createFileRoute } from "@tanstack/react-router";
import { AdjustmentsPage } from "@/components/cfo/control/AdjustmentsPage";

export const Route = createFileRoute("/control/adjustments")({
  head: () => ({ meta: [{ title: "Adjustments and Provisions · CityKart FP&A" }, { name: "description", content: "Governed changes: adjustments and provisions, corrections, the exception inbox. Sign-in required." }] }),
  component: AdjustmentsPage,
});
