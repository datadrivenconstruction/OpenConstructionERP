# Insert an assembly into a position, and move sections

Price an existing position from an assembly, and reorder the bill without losing your work.

## Insert an assembly

1. In the bill of quantities, open the row menu of a position and choose **Insert assembly**.
2. Pick the assembly. The dialog lists its components with quantity, rate and amount, and shows the rate of the position now and after the change.
3. Set the **Quantity factor** if needed. It multiplies every component quantity, for example 1.1 for 10 % waste.
4. If the position already has resources, choose **Replace them** or **Add the assembly to them**. Resources entered for the whole position can only be replaced.
5. Choose **Insert into position**. The number, text and quantity stay; resources and unit rate come from the assembly. A toast offers **Undo**.

The dialog warns when the assembly unit differs from the position unit, when its currency differs from the project, and when the assembly has no components. Positions in a read-only bill do not offer the action.

## Move sections and lines

Drag a section or a line to a new place. The whole bill is saved in the new order, and dropping on a nested row places the item next to the section that holds it, so a moved section no longer jumps back.
