# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A group that had no value is not a group whose value says so.

``_group_key`` turns one grouped column's value into the key it takes in a
KPI's breakdown, and it answered ``"(unset)"`` for a NULL. That is a data
value, spelled the way a person would spell one, and both grouped paths
assign into a dict keyed by it:

* ``_evaluate_top_by``  - ``breakdown[_group_key(grp)] = {...}``
* ``evaluate_spec``     - ``result.breakdown[key] = str(_fold(...))``

So a table holding rows with no value in the grouped column *and* rows
whose value is literally the text ``(unset)`` produced one breakdown entry
where there were two groups, and the later write won. A group vanished
from the KPI and the aggregate stopped decomposing into its parts. This
was found while cleaning Python out of the report writers, where the same
string was read as a hardcoded English label; the label is the smaller
half of it.

The replacement is a reserved key rather than a translated word. A word
cannot be localised once it is a dict key - by then it is indistinguishable
from a real group value like ``m3`` - whereas a name a consumer can test
for is mapped to whatever label that consumer speaks. It is reserved and
not impossible: a row whose group value is literally ``__null__`` collides
in exactly the way ``(unset)`` did. That is the trade, taken knowingly,
against an empty string (which collides with a genuine empty-string group,
and merges two groups that a NULL check in SQL keeps apart) and against a
word (which collides with prose somebody typed).

Run:
    cd backend
    python -m pytest tests/unit/test_bi_dashboards_a_null_group_is_not_a_data_value.py -v
"""

from __future__ import annotations

from app.modules.bi_dashboards.kpi_spec import _group_key


def test_a_null_group_is_not_the_same_key_as_a_group_named_unset() -> None:
    """Both paths write into ``breakdown[key]``, so an equal key loses a group."""
    keys = {_group_key(None), _group_key("(unset)")}
    assert len(keys) == 2, (
        f"a NULL group and a group whose value is the text '(unset)' both key on {_group_key(None)!r}, "
        f"so whichever is written second overwrites the other and one group is lost from the breakdown"
    )


def test_the_key_for_a_null_group_is_a_name_a_consumer_can_recognise() -> None:
    """A caller has to be able to tell the absent group from a real one.

    Imported here rather than at the top of the file so that the collision
    above is what fails when the collision is what is broken.
    """
    from app.modules.bi_dashboards.kpi_spec import NULL_GROUP_KEY

    assert _group_key(None) == NULL_GROUP_KEY


def test_a_group_that_has_a_value_still_keys_on_that_value() -> None:
    """The control: only the absent case changes."""
    assert _group_key("m3") == "m3"
    assert _group_key(0) == "0"
    assert _group_key(False) == "False"
