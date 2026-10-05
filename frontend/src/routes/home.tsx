import { createFileRoute } from "@tanstack/react-router";
import { Landing } from "@/components/home/Landing";

export const Route = createFileRoute("/home")({
  head: () => ({
    meta: [
      { title: "Analytics Home · CityKart" },
      { name: "description", content: "Finance, Operations and Merchandising reports in one place, each marked with the data behind it." },
      { property: "og:title", content: "Analytics Home · CityKart" },
      { property: "og:description", content: "Finance, Operations and Merchandising reports, kept separate." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: Landing,
});
