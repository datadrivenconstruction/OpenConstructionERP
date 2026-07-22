// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Reconcile a supplier statement".
//
// Match a supplier's monthly statement against your own purchase ledger, resolve
// the differences - missing invoices, unapplied credits, disputed charges - and
// settle the agreed balance. Content strings key plus inline English default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "reconcile-a-supplier-statement",
  order: 1026,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  icon: "Scale",
  titleKey: "cases.reconcile_a_supplier_statement.title",
  titleDefault: "Reconcile a supplier statement",
  descKey: "cases.reconcile_a_supplier_statement.desc",
  descDefault:
    "Match a supplier's monthly statement against your own purchase ledger, resolve the differences - missing invoices, unapplied credits, disputed charges - and settle the balance both sides agree.",
  longDescKey: "cases.reconcile_a_supplier_statement.longdesc",
  longDescDefault:
    "A supplier statement is their view of the account; your ledger is yours, and they rarely match. The gap hides double-charged deliveries, credits that never landed and invoices for goods you returned. Reconciling it is quiet money that a busy team leaves on the table every month.",
  estMinutes: 10,
  steps: [
    {
      id: "gather",
      icon: "FileSpreadsheet",
      inputs: [
        { labelKey: "cases.reconcile_a_supplier_statement.step.gather.in.statement", label: "Supplier statement" },
        { labelKey: "cases.reconcile_a_supplier_statement.step.gather.in.orders", label: "Orders and invoices" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_a_supplier_statement.step.gather.out.account", label: "Account assembled" },
      ],
      titleKey: "cases.reconcile_a_supplier_statement.step.gather.title",
      titleDefault: "Gather the account",
      whatKey: "cases.reconcile_a_supplier_statement.step.gather.what",
      whatDefault:
        "Bring together the supplier statement and your own orders, delivery records and invoices for the account, so both sides of the ledger are in front of you.",
      whyKey: "cases.reconcile_a_supplier_statement.step.gather.why",
      whyDefault:
        "You cannot reconcile what you cannot see side by side. Assembling both views first is what turns a vague sense that the account is wrong into a line-by-line comparison.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "match",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.reconcile_a_supplier_statement.step.match.in.account", label: "Both ledgers" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_a_supplier_statement.step.match.out.differences", label: "Differences flagged" },
      ],
      titleKey: "cases.reconcile_a_supplier_statement.step.match.title",
      titleDefault: "Match line by line",
      whatKey: "cases.reconcile_a_supplier_statement.step.match.what",
      whatDefault:
        "Match the statement lines against your ledger and flag everything that does not tie: an invoice they show and you do not, a credit you expected, a charge for a returned load.",
      whyKey: "cases.reconcile_a_supplier_statement.step.match.why",
      whyDefault:
        "The differences are the whole point. A statement that matches needs no work; it is the lines that do not tie that hold the overcharge or the missing credit worth chasing.",
      moduleLabel: "Finance",
      moduleLabelKey: "finance.title",
      to: "/projects/:projectId/finance",
    },
    {
      id: "resolve",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.reconcile_a_supplier_statement.step.resolve.in.differences", label: "Flagged differences" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_a_supplier_statement.step.resolve.out.agreed", label: "Agreed balance" },
      ],
      titleKey: "cases.reconcile_a_supplier_statement.step.resolve.title",
      titleDefault: "Resolve the differences",
      whatKey: "cases.reconcile_a_supplier_statement.step.resolve.what",
      whatDefault:
        "Work each difference to a conclusion with the supplier: chase the missing credit, dispute the wrong charge, raise the invoice you owe, until the account balances to an agreed figure.",
      whyKey: "cases.reconcile_a_supplier_statement.step.resolve.why",
      whyDefault:
        "An unresolved difference does not go away, it compounds into next month's statement. Clearing each one at source keeps the account clean and stops small errors becoming a tangled dispute.",
      moduleLabel: "Reconciliation",
      moduleLabelKey: "nav.reconciliation",
      to: "/projects/:projectId/reconciliation",
    },
    {
      id: "settle",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.reconcile_a_supplier_statement.step.settle.in.agreed", label: "Agreed balance" },
      ],
      outputs: [
        { labelKey: "cases.reconcile_a_supplier_statement.step.settle.out.paid", label: "Cleared account" },
      ],
      titleKey: "cases.reconcile_a_supplier_statement.step.settle.title",
      titleDefault: "Settle the balance",
      whatKey: "cases.reconcile_a_supplier_statement.step.settle.what",
      whatDefault:
        "Release payment for the reconciled balance, so you pay what you genuinely owe on time and neither overpay nor hold up a supplier over a figure that is now agreed.",
      whyKey: "cases.reconcile_a_supplier_statement.step.settle.why",
      whyDefault:
        "Paying a clean, agreed balance protects your credit terms and your reputation with the supplier. It also closes the account so the next statement starts from a figure you both trust.",
      moduleLabel: "Finance",
      moduleLabelKey: "finance.title",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
