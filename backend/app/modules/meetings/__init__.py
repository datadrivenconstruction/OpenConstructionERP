"""Meetings module.

Meeting minutes management — progress, design, safety, subcontractor,
kickoff, and closeout meetings with agendas, attendees, and action items.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.meetings.permissions import register_meetings_permissions

    register_meetings_permissions()
