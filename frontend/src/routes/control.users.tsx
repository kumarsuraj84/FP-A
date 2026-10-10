import { createFileRoute } from "@tanstack/react-router";
import { UsersPage } from "@/components/cfo/control/UsersPage";

export const Route = createFileRoute("/control/users")({
  head: () => ({ meta: [{ title: "Users · CityKart FP&A" }, { name: "description", content: "Governed changes: adjustments and provisions, corrections, the exception inbox. Sign-in required." }] }),
  component: UsersPage,
});
