import { createFileRoute } from "@tanstack/react-router";
import { ProfilePage } from "@/components/cfo/DeepPages";

export const Route = createFileRoute("/profile")({
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
