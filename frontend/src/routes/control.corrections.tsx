import { createFileRoute } from "@tanstack/react-router";
import { CorrectionsPage } from "@/components/cfo/control/CorrectionsPage";

export const Route = createFileRoute("/control/corrections")({
  head: () => ({ meta: [{ title: "Corrections · CityKart FP&A" }, { name: "description", content: "Governed changes: adjustments and provisions, corrections, the exception inbox. Sign-in required." }] }),
  component: CorrectionsPage,
});
