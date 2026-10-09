import { createFileRoute } from "@tanstack/react-router";
import { ExpensesPage } from "@/components/cfo/expenses/ExpensesPage";
import { validateExpSearch } from "@/components/cfo/expenses/expensesUrl";

export const Route = createFileRoute("/mgmt_/dc-expenses")({
  validateSearch: validateExpSearch,
  head: () => ({
    meta: [
      { title: "DC Expenses · CityKart FP&A" },
      { name: "description", content: "DC cost of the SubCo and HoldCo warehouses by head, site and ledger, down to the voucher." },
      { property: "og:title", content: "DC Expenses · CityKart FP&A" },
      { property: "og:description", content: "DC cost of the SubCo and HoldCo warehouses by head, site and ledger, down to the voucher." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: () => <ExpensesPage scope="dc" />,
});
