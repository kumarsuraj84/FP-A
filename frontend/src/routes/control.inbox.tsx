import { createFileRoute } from "@tanstack/react-router";
import { InboxPage } from "@/components/cfo/control/InboxPage";

export const Route = createFileRoute("/control/inbox")({
  head: () => ({ meta: [{ title: "Exception Inbox · CityKart FP&A" }, { name: "description", content: "Governed changes: adjustments and provisions, corrections, the exception inbox. Sign-in required." }] }),
  component: InboxPage,
});
