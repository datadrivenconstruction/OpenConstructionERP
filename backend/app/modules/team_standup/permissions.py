# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Team Standup permission declarations.

Everything is viewer-level on purpose: a standup entry is a person's own
status line, not project data, and nobody on the team should be locked
out of posting their own update or replying to a teammate. That extends
to the delivery board and its config - the stages, activities and
waiting-on vocabulary belong to the whole team ("every team ends up with
its own vocabulary"), and every change is logged server-side by name,
which is the accountability rail. The real write rails are in the
service - you can only ever write YOUR OWN entry, and only delete your
own comment (admins may moderate).

``team_standup.metrics`` is the ONE exception, and deliberately so. The
metrics rollup is not a status line - it is management information ABOUT
people: how many tasks each person closed and how long they took, how
many standups they posted, how many blockers they raised, which jobs and
which ERP modules their hours went to, and an attendance table saying
when each person signed in, when they were last seen, how long they were
active and whether they are still on. Nobody on the team should be able
to read that about a colleague, so it sits at MANAGER. Admins reach it
through the usual admin bypass in ``RequirePermission``.

That gate is on READING the aggregate only. Writing your own presence
(``POST /presence/ping`` and ``POST /presence/session``) stays on
``team_standup.read``, because every signed-in user has to be able to
report where they are or the table has nothing in it - see the comment
on those two routes in ``metrics_router.py`` before "tidying" them onto
the metrics permission.

So does READING today's presence (``GET /presence/today``), which is a
separate, deliberately tiny endpoint: user, name, online, first and last
seen, today only, for the people the caller can already see. Knowing a
colleague is on site or online is ordinary team awareness and the whole
point of the project hub's team tile - gating it at manager blanked that
tile for every ordinary team member without protecting anything, because
none of the management information is in it.
"""

from app.core.permissions import Role, permission_registry


def register_team_standup_permissions() -> None:
    permission_registry.register_module_permissions(
        "team_standup",
        {
            "team_standup.read": Role.VIEWER,
            "team_standup.post": Role.VIEWER,
            "team_standup.comment": Role.VIEWER,
            "team_standup.tasks": Role.VIEWER,
            "team_standup.config": Role.VIEWER,
            # Reading the team-wide rollup + attendance. Manager-level:
            # see the module docstring above for why this one is not
            # viewer-level like the rest.
            "team_standup.metrics": Role.MANAGER,
        },
    )


register_team_standup_permissions()
