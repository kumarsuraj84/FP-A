import { createFileRoute } from "@tanstack/react-router";
import { MappingPage } from "@/components/cfo/control/MappingPage";

export const Route = createFileRoute("/control/mapping")({
  head: () => ({ meta: [{ title: "Mapping Governance · CityKart FP&A" }, { name: "description", content: "Versioned, effective-dated mapping rules: ledger to management group, site to location type. Sign-in required." }] }),
  component: MappingPage,
});
