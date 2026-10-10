import { createFileRoute, redirect } from "@tanstack/react-router";
import { ProfilePage } from "@/components/cfo/DeepPages";

export const Route = createFileRoute("/profile")({
  // these workspaces exist only inside a drill (the context is in the address): without one there is nothing to show, so go home at once instead of rendering the Command Center under this address
  beforeLoad: ({ search }) => {
    if (!(search as { drill?: string }).drill) throw redirect({ to: "/" });
  },
  head: () => ({
    meta: [
      { title: "Entity Profile · CityKart FP&A" },
      { name: "description", content: "Entity Profile workspace for the CFO Operating System. Demo data." },
      { property: "og:title", content: "Entity Profile · CityKart FP&A" },
      { property: "og:description", content: "Entity Profile workspace. Demo data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: ProfilePage,
});
