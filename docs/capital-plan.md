# Capital plan

Which projects fit the money, and what happens if we delay one.

Open **Portfolio > Capital plan** (`/capital-plan`). The module works for any owner, municipality or developer ranking projects against a limited yearly budget. It has no country logic; national funding rules belong in a country pack.

## Set it up

1. **Create a plan**: a name, a currency, a start year and the number of years (1 to 15).
2. **Enter the budget**: the Envelope row at the bottom of the grid. One number per year. Several funding sources in one year (for example a bond and a grant) can be loaded through the API and are shown as a sum.
3. **Import projects**: copies the projects filed under the plan's portfolio node. The cost is the latest approved bill of quantities, else the project budget, else the contract value; start and duration come from the project's planned dates. Everything can be edited afterwards.

## Read the grid

Each row is a project, each column a year. A cell is the part of the cost spent in that year (even by default, or your own shares per year). Under the grid:

- **Envelope**: the money available that year.
- **Demand**: the cost of all projects that are not deferred.
- **Gap**: envelope minus demand. Red means that year is over the budget.

## Try a what-if

Press **New scenario** to copy the current scenario, then move a start year with the arrows, change a priority or defer a project. The original is never changed. **Compare** shows the change in demand and gap per year and the projects whose status or start year differ.

## Suggest funding

**Suggest funding** orders projects by priority (1 is highest), then score, then cost, and funds each one that fits every year of its spend. A project that does not fit stays proposed, with the first year that overflows. It is a proposal with a confidence value: nothing changes until you press **Apply**.

## Checks

Listed under the grid: phasing that does not add up to 1 or does not match the duration, spend outside the plan years, a year over the budget, a year with no budget, a project with no cost, the same project twice in one scenario, a second baseline, and a project whose currency differs from the plan.

## Export

**Export** downloads the scenario as an Excel file with the years as columns.

## Permissions

Everyone with read access sees plans. Changing a plan needs the manager role.

## Not in this version

Net present value and internal rate of return ranking, multi-criteria scoring models, national funding rules and risk simulation.
