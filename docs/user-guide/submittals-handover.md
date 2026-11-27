# Submittals: ball in court, distribution and closing

Keep track of who must act on a submittal next, who gets a copy, and when it is finished.

Open **Documents > Submittals** and open a submittal.

## Hand it over

1. In **Ball in court and distribution**, choose the person who has to act next in **Ball in court**. Reassign it whenever the item changes hands.
2. Add everyone who should receive the submittal for information to the **Distribution list**. The list shows as "Distribution: names" on the item.
3. Once the submittal is decided (approved, approved as noted or rejected), use **Close** to finish it. Closing is limited to roles allowed to update submittals.

Only people who can open the project can be picked.

## What the validation rules warn about

- `submittal.ball_in_court_assigned`: an open submittal has no ball in court.
- `submittal.distribution_present`: an open submittal has an empty distribution list.
- `submittal.people_have_project_access`: an error when the ball holder or a distribution entry cannot open the project.
