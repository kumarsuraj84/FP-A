# Reconciliation
Framework: `app/recon/framework.py` — Source vs Mart vs KPI, tolerance exactly ₹0, explanations recorded not rounded; an empty report never passes; explained variances are "accepted" but do NOT pass the gate.
Required checks: total debit, total credit, revenue, major expenses, site totals, month totals, creditor outstanding, advances; scopes: company, one month, several stores, several GLs, several vendors.
**Results: NONE.** No source data was reachable, so no reconciliation evidence exists. Gate status: **NOT PASSED**. Unit tests only prove the framework's logic.
