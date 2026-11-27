# Cost types and commitments

See budget, committed cost, actual cost and forecast for every cost code, split into labour, material, equipment, subcontract and other. Book each purchase order line and subcontract agreement to the budget line it spends, and let the invoice check stop a bill that exceeds its order.

Open **Cost control > Cost model** and choose the **By cost type** tab.

## Split the budget by cost type

1. Generate the budget from your bill of quantities. Each position becomes one budget line per cost type, cut by the resources of the position.
2. Open **By cost type**. Rows are cost codes, each type has its own column group, and the last row holds the totals. Columns show budget, committed, actual, forecast, estimate at completion and variance.
3. Hover a figure to see where it comes from, for example the purchase orders and subcontracts booked to that budget line, or a committed value typed on the line.

An empty grid means the budget has no lines yet; generate it from the bill first.

## Book orders and subcontracts to a budget line

1. Open a purchase order or a subcontract agreement.
2. In the **Budget line** field of each line, pick the line it spends. The committed value rolls into that budget line and shows in the grid.
3. Leave **Not booked to a budget line** when the spend has no budget yet.

The field is disabled, with the reason as tooltip, for roles that can read budget lines but not change them, and for orders that are already issued.

## Invoices against the commitment

When you approve a supplier invoice the platform compares it with the order or subcontract agreement it bills. Approval is refused when the invoice is above the open commitment (order or agreement value plus approved changes, less what is already invoiced), is in another currency, repeats a supplier invoice number, or is paid before it is dated. An invoice can link a subcontract agreement, and retention below the agreed share is flagged. The invoice form shows the commitment and the reason, and the Approve button is disabled with that reason. A scheduled payment date next to the due date is what payment runs and the cash-flow forecast read first.

## What the validation rules warn about

- `cost_types.position_unsplit`: a bill position had no resources, so its budget line went whole to "other".
- `cost_types.unknown_type`: a budget line has a category outside labour, material, equipment, subcontract and other.
- `invoice_posting.*`: invoice above the open commitment, different currency, retention below the agreed share, duplicate or possibly duplicate supplier number, payment date before the invoice date.
