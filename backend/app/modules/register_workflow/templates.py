# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Workflow spines, field specs and the action library.

The spine every item starts with, the fields its raise form asks for, and
the actions a person can slot in when the job does not run the way the
spine assumed - which is most of the time.
"""

from __future__ import annotations

from typing import Any

#: The six registers this platform runs.
KINDS: tuple[str, ...] = ("rfi", "rfq", "order", "variation", "delay", "toolbox")

KIND_LABELS: dict[str, str] = {
    "rfi": "Request for Information",
    "rfq": "Request for Quotation",
    "order": "Purchase Order",
    "variation": "Variation",
    "delay": "Delay Notice",
    "toolbox": "Toolbox Talk",
}

#: Reference prefixes, per kind (REG-RFI-000001 style). The platform's own
#: registers mint their numbers; these are the display prefixes for
#: workflow-only items.
KIND_PREFIX: dict[str, str] = {
    "rfi": "RFI",
    "rfq": "RFQ",
    "order": "ORD",
    "variation": "VO",
    "delay": "DEL",
    "toolbox": "TBX",
}

#: Who a kind is addressed to: multi (several suppliers, one draft each),
#: single (one supplier), client (a distribution list), none (internal).
KIND_RECIPIENT: dict[str, str] = {
    "rfi": "any",
    "rfq": "multi",
    "order": "single",
    "variation": "client",
    "delay": "client",
    "toolbox": "none",
}

#: The evidence section each register collects.
KIND_SECTION: dict[str, str] = {
    "rfi": "Response",
    "rfq": "Quotes received",
    "order": "Delivery record",
    "variation": "Approval",
    "delay": "Evidence",
    "toolbox": "Sign-on",
}

#: One sentence that opens the register's email.
KIND_INTRO: dict[str, str] = {
    "rfi": "Please provide a response to the question below.",
    "rfq": "Please provide a quotation and lead time for the materials listed below.",
    "order": "Please find our order below and confirm acceptance and delivery date.",
    "variation": "Please find our variation below for your approval.",
    "delay": "Please find our notice of delay below.",
    "toolbox": "Toolbox talk record, for your files.",
}


def step(name: str) -> dict[str, Any]:
    return {"t": "step", "name": name}


def gate(name: str, owner: str = "") -> dict[str, Any]:
    return {"t": "gate", "name": name, "owner": owner}


def route(question: str, branches: dict[str, list[str]]) -> dict[str, Any]:
    return {"t": "route", "name": question, "branches": branches}


# ── The spines ───────────────────────────────────────────────────────────

FLOWS: dict[str, list[dict[str, Any]]] = {
    "rfi": [
        step("Question drafted and clear"),
        step("Drawings / marked-up sketch attached"),
        gate("Reviewed before issue", "PM"),
        step("Sent to the client / consultant"),
        step("Response received in writing"),
        route(
            "Does the answer change scope, cost or program?",
            {
                "No change - action it": ["Answer actioned in the works", "Closed out"],
                "Change - raise a variation": [
                    "Variation raised (link the VO no.)",
                    "Client instruction in writing",
                    "Closed out - carried by the VO",
                ],
                "Unclear - escalate": [
                    "Escalated to the superintendent",
                    "Clarification received",
                    "Answer actioned in the works",
                    "Closed out",
                ],
                "No response - chase": [
                    "Follow-up sent",
                    "Escalated to the superintendent",
                    "Delay notice raised if it holds work",
                    "Closed out",
                ],
            },
        ),
    ],
    "rfq": [
        step("Scope and quantities defined"),
        step("Drawings / specs attached"),
        gate("Package checked before it goes out", "PM"),
        step("Sent to at least two suppliers"),
        step("Quotes received"),
        # THE COMPARISON GATE - enforced, not advisory: over the threshold
        # it refuses to pass until enough real PRICES are in.
        gate("Quotes compared - enough prices in", "PM"),
        route(
            "Where does the package land?",
            {
                "Award it - raise the order": [
                    "Supplier selected",
                    "Order card raised",
                    "Closed out",
                ],
                "Re-scope and re-issue": [
                    "Scope corrected",
                    "Re-issued to suppliers",
                    "Quotes received",
                    "Closed out",
                ],
                "Hold - not proceeding yet": ["Reason recorded", "Closed out - on hold"],
                "Cancel": ["Suppliers advised", "Closed out - cancelled"],
            },
        ),
    ],
    "order": [
        step("Pricing confirmed against the quote"),
        gate("Order approved before it is placed", "PM"),
        step("PO raised in the job-management system"),
        step("Sent to the supplier"),
        step("Order acknowledged by the supplier"),
        step("Delivery date confirmed"),
        route(
            "How did the delivery land?",
            {
                "Delivered in full": [
                    "Checked against the docket",
                    "Invoice matched to the PO",
                    "Closed out",
                ],
                "Short or damaged": [
                    "Shortage / damage photographed",
                    "Supplier notified in writing",
                    "Replacement or credit agreed",
                    "Invoice matched to the PO",
                    "Closed out",
                ],
                "Late - it hits the program": [
                    "Delay notice raised",
                    "New date confirmed",
                    "Delivered and checked",
                    "Closed out",
                ],
            },
        ),
    ],
    "variation": [
        step("Scope of change confirmed on site"),
        step("Priced"),
        gate("Margin and scope reviewed", "PM"),
        step("Submitted to the client"),
        route(
            "What did the client come back with?",
            {
                "Approved - VO / PO number received": [
                    "Approval in writing attached",
                    "Works instructed to the crew",
                    "Invoiced",
                    "Closed out",
                ],
                "Approved in principle - proceed at risk": [
                    "Written direction attached",
                    "Risk accepted by the PM",
                    "Formal approval chased",
                    "Invoiced",
                    "Closed out",
                ],
                "Rejected": [
                    "Reason recorded in writing",
                    "Works stopped or reverted",
                    "Closed out - rejected",
                ],
                "No answer - chase": [
                    "Follow-up sent",
                    "Escalated to the superintendent",
                    "Delay notice raised if it holds work",
                    "Closed out",
                ],
            },
        ),
    ],
    "delay": [
        step("Logged the same day with times"),
        step("Photos / evidence attached"),
        gate("Notice reviewed before issue", "PM"),
        step("Client notified in writing"),
        step("Acknowledgement received"),
        route(
            "What are we claiming?",
            {
                "Time only - EOT": [
                    "EOT claim submitted",
                    "Added to the Lost Time Register",
                    "Closed out",
                ],
                "Time and cost": [
                    "Cost impact assessed",
                    "EOT and cost claim submitted",
                    "Added to the Lost Time Register",
                    "Closed out",
                ],
                "Record only - no claim": [
                    "Added to the Lost Time Register",
                    "Closed out - record only",
                ],
            },
        ),
    ],
    "toolbox": [
        step("Talk delivered on site"),
        step("Sign-on sheet attached"),
        step("Site-specific hazards covered"),
        gate("Actions closed out or escalated", "Site lead"),
    ],
}


# ── The action library ───────────────────────────────────────────────────
# The spine is what every item STARTS with; no two RFIs actually run the
# same, so a person slots the next action in where they are. Same three
# shapes, so gates/stats/ball-in-court keep working on an added action.

COMMON_ACTIONS: list[dict[str, Any]] = [
    step("Follow-up sent"),
    step("Chased by phone"),
    step("Escalated to the superintendent"),
    step("Discussed at the site meeting"),
    step("Put on hold - awaiting instruction"),
    step("Site inspection carried out"),
    step("Photos / evidence attached"),
    step("Marked up drawing issued"),
    gate("Reviewed by the PM", "PM"),
    gate("Client sign-off received", "Client"),
    step("Closed out"),
]

#: Actions that START another register - the step grows a "raise the next
#: one" button that opens that register's form prefilled from this item.
RAISE_ACTIONS: dict[str, dict[str, Any]] = {
    "variation": step("Variation raised (link the VO no.)"),
    "delay": step("Delay notice raised"),
    "order": step("Order card raised"),
    "rfq": step("RFQ raised for pricing"),
    "rfi": step("RFI raised to the client"),
}


def actions_for(kind: str) -> list[dict[str, Any]]:
    """The next-action menu for one kind: its own spine steps, the common
    library, and the cross-register raises."""
    # ROUTES STAY IN THE LIBRARY. Stripping them meant a job that hit a
    # SECOND fork could not be modelled at all: it degraded to flat steps
    # and lost the branch record, which is the one thing a decision
    # exists to keep. A route carries its branches with it, so adding one
    # adds a real fork rather than a step with a question mark in its name.
    own = list(FLOWS.get(kind, []))
    raises = [v for k, v in RAISE_ACTIONS.items() if k != kind]
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in [*own, *COMMON_ACTIONS, *raises]:
        if item["name"] in seen:
            continue
        seen.add(item["name"])
        out.append(item)
    return out


# ── Raise-form field specs ───────────────────────────────────────────────
# (label, type, is_due_date, is_internal). ``internal`` fields are
# card-only: the money rail strips them from every email.

FIELDS: dict[str, list[tuple[str, str, bool, bool]]] = {
    "rfi": [
        ("Responsible", "text", False, False),
        ("Ball in court", "text", False, False),
        ("Discipline", "select", False, False),
        ("Drawing / spec reference", "text", False, False),
        ("Question", "area", False, False),
        ("Proposed resolution", "area", False, False),
        ("Impact if unanswered", "text", False, False),
        ("Response required by", "date", True, False),
        ("Notes / additional information", "area", False, False),
    ],
    "rfq": [
        ("Responsible", "text", False, False),
        ("Ball in court", "text", False, False),
        ("Package", "text", False, False),
        ("Materials / scope required", "area", False, False),
        ("Delivery required by", "date", False, False),
        ("Delivery to", "text", False, False),
        ("Site contact", "text", False, False),
        ("Delivery window / site hours", "select", False, False),
        ("Delivery notes / access", "area", False, False),
        # CARD-ONLY but REQUIRED: it sets how many quotes this package
        # must have before the compare gate will pass.
        ("Estimated value $", "money", False, True),
        ("Quotes due", "date", True, False),
        ("Notes / additional information", "area", False, False),
    ],
    "order": [
        ("Responsible", "text", False, False),
        ("Ball in court", "text", False, False),
        ("Supplier", "text", False, False),
        ("Our PO #", "text", False, False),
        ("Value $", "money", False, False),
        ("Delivery to", "text", False, False),
        ("Site contact", "text", False, False),
        ("Delivery window / site hours", "select", False, False),
        ("Delivery notes / access", "area", False, False),
        ("ETA", "date", True, False),
        ("Notes / additional information", "area", False, False),
    ],
    "variation": [
        ("Responsible", "text", False, False),
        ("Ball in court", "text", False, False),
        ("Client instruction ref", "text", False, False),
        ("Description of change", "area", False, False),
        ("Scope impact", "area", False, False),
        ("Program impact (days)", "text", False, False),
        ("Cost $", "money", False, True),
        ("Sell $", "money", False, True),
        ("Margin", "text", False, True),
        ("Status", "select", False, False),
        ("Client approval required by", "date", True, False),
        ("Notes / additional information", "area", False, False),
    ],
    "delay": [
        ("Responsible", "text", False, False),
        ("Ball in court", "text", False, False),
        ("Date of delay", "date", False, False),
        ("Duration (hrs)", "text", False, False),
        ("Crew affected (names)", "text", False, False),
        ("Cause", "select", False, False),
        ("Instruction from", "text", False, False),
        ("Work that stopped", "area", False, False),
        ("Supporting documentation", "area", False, False),
        ("Cost impact $", "money", False, True),
        ("Client to be notified by", "date", True, False),
        ("Notes / additional information", "area", False, False),
    ],
    "toolbox": [
        ("Responsible", "text", False, False),
        ("Ball in court", "text", False, False),
        ("Topic", "text", False, False),
        ("Date held", "date", False, False),
        ("Presented by", "text", False, False),
        ("Attendees", "area", False, False),
        ("Hazards / changes discussed", "area", False, False),
        ("Actions to close out by", "date", True, False),
        ("Notes / additional information", "area", False, False),
    ],
}

#: Fields the raise form REFUSES to submit empty (RFQ only, ported: the
#: delivery block plus the value that sets the quote tier).
REQUIRED: dict[str, tuple[str, ...]] = {
    "rfq": ("Delivery to", "Site contact", "Delivery window / site hours", "Estimated value $"),
}

#: Locked vocabularies for ``select`` fields.
OPTIONS: dict[str, list[str]] = {
    "Discipline": [
        "Electrical",
        "Comms / data",
        "Fire services",
        "Mechanical",
        "Hydraulic",
        "Civil / structural",
        "Controls / automation",
    ],
    "Delivery window / site hours": [
        "Site hours 06:30-14:30",
        "Before 07:00 start",
        "Morning only",
        "Afternoon only",
        "Call site contact ahead",
    ],
    "Cause": [
        "Client instruction",
        "Site access",
        "Design change",
        "Weather",
        "Free-issue materials",
        "Other trades",
        "Industrial",
        "Other",
    ],
    "Status": ["Submitted", "Approved", "Rejected", "Withdrawn", "Superseded"],
}

#: Interlink map: raising ``target`` from a ``source`` item carries these
#: fields across, so a VO number is never typed twice.
LINKS: dict[str, dict[str, Any]] = {
    "variation": {"ref_into": "Client instruction ref", "narrative_into": "Description of change"},
    "delay": {"ref_into": "Instruction from", "narrative_into": "Work that stopped"},
    "order": {"ref_into": "Our PO #", "narrative_into": "Notes / additional information"},
    "rfq": {"ref_into": "Package", "narrative_into": "Materials / scope required"},
    "rfi": {"ref_into": "Drawing / spec reference", "narrative_into": "Question"},
}


def spec_for(kind: str) -> dict[str, Any]:
    """Everything the UI needs to render one register's raise form."""
    return {
        "kind": kind,
        "label": KIND_LABELS.get(kind, kind.upper()),
        "prefix": KIND_PREFIX.get(kind, kind.upper()),
        "recipient": KIND_RECIPIENT.get(kind, "none"),
        "evidence_section": KIND_SECTION.get(kind, "Evidence"),
        "intro": KIND_INTRO.get(kind, ""),
        "fields": [
            {
                "label": label,
                "type": ftype,
                "is_due": is_due,
                "internal": internal,
                "required": label in REQUIRED.get(kind, ()),
                "options": OPTIONS.get(label, []),
            }
            for (label, ftype, is_due, internal) in FIELDS.get(kind, [])
        ],
        "flow": FLOWS.get(kind, []),
        "actions": actions_for(kind),
    }
