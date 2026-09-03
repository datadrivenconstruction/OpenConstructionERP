# Register Workflow (`oe_register_workflow`)

The tier-one workflow spine behind **Comms Intelligence** — the source workflow app
Portfolio's registers, rebuilt on the platform's own modules.

## The item IS the native record

Raising a register item creates the platform's real record, not a copy:

| Kind | Native record | What that buys |
|---|---|---|
| `rfq` | `oe_rfq_rfq` | the tiered quote gate, comparison, award, ranked-table snapshot |
| `rfi` | `oe_rfi_rfi` | the native RFI register, ball-in-court, impact flags |
| `variation` | `oe_variations_request` | the variation register and its approval flow |
| `order` | `oe_procurement_po` | procurement, goods receipt, invoice matching |
| `delay`, `toolbox` | — | workflow-only (no native register on this platform) |

`linked_entity_type/id` ties them together and `native.enrich()` reads the
live facts back onto the register row, so the workspace shows one answer
from one source. A missing sibling module leaves an item workflow-only
rather than refusing the raise.

The **estimated value** typed on the RFQ raise form lands in the RFQ's
`metadata_.estimated_value`, which is exactly where the quote gate reads
its tier from — the number on the form is the number that decides how
many quotes the award will demand.

## The rails (all server-side, all tested)

- Steps complete **in order**; undo works in reverse only
- **A gate can never be marked not-required** — "a hold point somebody signs"
- **A route can't be ticked** — choose a branch and its steps are appended,
  so the record shows the path actually taken
- The RFQ compare gate calls the same `RFQService.quote_gate_status` the
  award enforces: one definition, every surface
- Passing a gate below its rule demands a written reason, kept forever
- Completed steps are immutable history; a new action slots in after them
- Raising from a step closes the loop both ways (`→ ORD-001`)
- **Deleted only while nobody has seen it**; anything already issued is
  *withdrawn* instead - and the reference is never re-issued either way

## Endpoints (`/api/v1/register-workflow/`)

`GET /spec` · `GET|POST /items` · `GET|PATCH|DELETE /items/{id}` ·
`POST /items/{id}/withdraw|reopen` ·
`POST /items/{id}/steps` · `GET /items/{id}/prefill/{kind}` ·
`POST /items/{id}/quotes` (compare panel) · `POST /items/{id}/award` ·
`POST /steps/{id}/complete|uncomplete|not-required|route` ·
`GET /summary`

Every item response carries `native` — the live RFQ number, quote gate,
bids and award — so the UI never stitches two modules' answers together.

### Raised in error: delete, or withdraw

`DELETE /items/{id}` erases an item **only** when nothing has left the
building: no send log, no captured replies, no quotes, no award, and
nothing raised from it. It takes the steps, the reciprocal links, the
native record and the evidence folder with it, and answers `204`.
Otherwise it refuses with `409 {error, reasons: [...]}` naming what
stops it ("This RFQ has been emailed to 3 suppliers and has 2 quotes -
withdraw it instead of deleting it.").

That record rail binds everybody, whatever permission they hold. Past
it, deleting is two-sided: **the person who raised it** may erase their
own unseen mistake with `register_workflow.update`, and **anyone else**
needs the manager-level `register_workflow.delete`. Otherwise `403`,
same detail shape ("… was raised by another person - only a manager can
delete it. You can withdraw it instead.").

`POST /items/{id}/withdraw {reason}` is the path for everything else: a
third `status` value `withdrawn` (reason validated the way a gate
override is), stamped on the item as `withdrawn_reason|_at|_by` and
appended to the step trail. A withdrawn item leaves the open list, the
deadline sweep, the tracking board, the overdue clock and the
with-them/with-us counts, shows in the closed view carrying its reason,
and refuses every further mutation until `POST /items/{id}/reopen
{reason}` puts it back. **The counter never rolls back** - deleting the
newest RFQ leaves the next raise on the next number.

## Tests

`backend/tests/modules/register_workflow/` — 22 tests: template integrity
(every kind has a spine, a gate and a route; money fields marked
internal), raise validation, all four step rails, route branching, action
insertion, interlink prefill both ways, per-kind numbering, summary
counts, and the native bridge (RFQ/RFI creation, live gate figures, a
corrected price updating rather than duplicating a column).
