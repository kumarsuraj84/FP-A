import { createFileRoute } from "@tanstack/react-router";
import { ExpensesPage } from "@/components/cfo/expenses/ExpensesPage";
import { validateExpSearch } from "@/components/cfo/expenses/expensesUrl";

export const Route = createFileRoute("/mgmt_/store-expenses")({
  validateSearch: validateExpSearch,
  head: () => ({
    meta: [
      { title: "Store Expenses · CityKart FP&A" },
      { name: "description", content: "Store expenses by head (rent, employee cost, power and fuel, advertisement, freight forwarding, other expenses), by store and ledger, down to the voucher." },
      { property: "og:title", content: "Store Expenses · CityKart FP&A" },
      { property: "og:description", content: "Store expenses by head (rent, employee cost, power and fuel, advertisement, freight forwarding, other expenses), by store and ledger, down to the voucher." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: () => <ExpensesPage scope="store" />,
});
