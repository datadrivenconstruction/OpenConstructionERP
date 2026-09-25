# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What the BOQ activity feed shows for a stored entry.

Kept apart from ``events.py`` (which registers bus handlers when imported) so
the repository, the service and the event handler can share it without side
effects.
"""

#: Activity actions that record a read, not a change. Opening a screen is not
#: something a person did to the bill, so these never belong in its feed. The
#: cost breakdown used to publish ``boq.cost_breakdown.computed`` on every GET,
#: which put a row in Recent Activity each time the editor loaded; the publish
#: is gone, and rows written before that are kept out of the listing here.
READ_ONLY_ACTIVITY_ACTIONS: frozenset[str] = frozenset({"cost_breakdown.computed"})


def humanize_action(action: str) -> str:
    """Readable text for an activity action that has no description of its own.

    ``cost_breakdown.computed`` reads "Cost breakdown computed". This is the
    fallback for an event nobody wrote a sentence for; without it the feed
    printed the dotted event name itself, which reads like an untranslated key.
    """
    words = action.removeprefix("boq.").replace(".", " ").replace("_", " ").split()
    text = " ".join(words)
    return text[:1].upper() + text[1:] if text else action


def activity_description(action: str, description: str | None) -> str:
    """The text the feed shows for a stored entry.

    Entries written before the fallback existed carry the raw event name as
    their description (``boq.<action>`` or the bare action). Those are shown
    humanized; every other description is returned as it was written.
    """
    text = (description or "").strip()
    if not text or text in (action, f"boq.{action}"):
        return humanize_action(action)
    return text
