import { createFileRoute } from "@tanstack/react-router";
import { SourceFixesPage } from "@/components/cfo/control/SourceFixesPage";

export const Route = createFileRoute("/control/source-fixes")({
  head: () => ({ meta: [{ title: "Source fixes · CityKart FP&A" }, { name: "description", content: "Recurring corrections and mapping changes ranked for the extraction team. Advisory only. Sign-in required." }] }),
  component: SourceFixesPage,
});
