# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What the meetings module does with its type list, beyond agreeing on it.

The cross-layer agreement, that the Python tuple, the TypeScript array and the
locale files all say the same words, is held for every module at once in
``test_module_vocabularies_close_across_layers.py``. What lives here is the
part only this module has: a meeting type can be guessed from a transcript, and
a type nothing can guess is a type the import path can never offer. That is not
a crash, it is an option in the API that no feature ever produces.
"""

import pytest

from app.modules.meetings.router import _AI_MEETING_PROMPT, _infer_meeting_type
from app.modules.meetings.schemas import MEETING_TYPES

# One transcript fragment per type, so that adding a type to the tuple and
# leaving the classifier alone fails here rather than shipping a type the
# import path can never produce. The fragments are deliberately short and
# ordinary; they are not tuned to pass.
_TRANSCRIPT_BY_TYPE: dict[str, str] = {
    "safety": "Toolbox talk on the scaffold edge protection, one near miss reported this week.",
    "design": "Design review of the revised stair detail, architect to reissue the drawing.",
    "subcontractor": "Trade coordination with the cladding subcontractor over their scope of work.",
    "kickoff": "Project kickoff, mobilization dates and site setup agreed with all parties.",
    "closeout": "Closeout walk, the punch list is down to nine items before handover.",
    "commercial": "Interim valuation number seven, the payment application and retention release.",
    "progress": "Weekly site walk, the slab pour is on programme and the crane arrives Monday.",
}


def test_the_keyword_classifier_can_reach_every_type():
    assert set(_TRANSCRIPT_BY_TYPE) == set(MEETING_TYPES), (
        "a type was added without a transcript fragment here, so nothing proves _infer_meeting_type can ever return it"
    )
    for meeting_type, transcript in _TRANSCRIPT_BY_TYPE.items():
        assert _infer_meeting_type(transcript) == meeting_type


def test_an_unremarkable_transcript_still_lands_on_progress():
    assert _infer_meeting_type("Attendance taken, minutes of the last meeting agreed.") == "progress"


@pytest.mark.parametrize("meeting_type", MEETING_TYPES)
def test_the_model_is_shown_the_whole_vocabulary(meeting_type: str):
    """The model can only answer with a type it was told about."""
    assert "__MEETING_TYPES__" not in _AI_MEETING_PROMPT, "the placeholder was never substituted"
    assert meeting_type in _AI_MEETING_PROMPT
