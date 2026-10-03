import { createFileRoute } from "@tanstack/react-router";
import { VendorProfilePage } from "@/components/cfo/creditors/VendorProfilePage";

export const Route = createFileRoute("/creditors_/vendor")({
  head: () => ({
    meta: [
      { title: "Vendor Financial Profile · CityKart FP&A" },
      { name: "description", content: "Vendor financial lifecycle, exposure trend, ageing migration, payment behaviour and open items. Demo data." },
      { property: "og:title", content: "Vendor Financial Profile · CityKart FP&A" },
      { property: "og:description", content: "Vendor financial profile. Demo data." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: VendorProfilePage,
});
