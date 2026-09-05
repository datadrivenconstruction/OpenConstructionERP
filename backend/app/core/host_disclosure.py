# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Keeping the server's own filesystem out of what an anonymous caller reads.

A few endpoints answer without credentials on purpose. A status check that
says whether a CAD converter is installed is one of them: the BIM page asks
for it, the desktop shell asks for it, and neither has a token to offer at
the moment it asks. That decision is about *reachability*, and it is a good
one. It says nothing about what may travel in the body.

An absolute path on the server does travel. On a default install the
converters live under the operator's home directory, so a field holding
``C:\\Users\\<account>\\.openestimator\\converters\\rvt_windows\\RvtExporter.exe``
publishes the home directory layout and the operating system account name of
whoever runs the process to anybody who can reach the port. The endpoint's
purpose survives without it: a caller asking whether a converter is installed
is answered by ``installed``, and does not need to be told where.

So the rule is not "close the route", it is "the path is for the operator".
An authenticated caller still gets it, because the Settings panel and the BIM
banner both display it and an operator fixing a broken install needs the
folder name. Everyone else gets the same answer with those fields emptied.

Redaction happens on a **copy**, never in place. Two of the three callers
answer out of a process-wide cache, and emptying the cached dict for an
anonymous request would empty it for the operator who asks next.
"""

from collections.abc import Mapping
from typing import Any

__all__ = ["without_host_fields"]


def without_host_fields(payload: Mapping[str, Any], blanks: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of ``payload`` with each key in ``blanks`` set to its placeholder.

    Keys absent from ``payload`` are left absent rather than introduced, so the
    response shape an anonymous caller sees is the shape it always had with the
    sensitive values emptied, not a different one that a client would have to
    learn. The placeholder is given per field because the fields differ in
    type: a path reads as ``None`` (the same value it already carries when
    nothing is installed) and a diagnostic message as ``""``.

    Args:
        payload: The response fragment as the operator may read it.
        blanks: ``{field name: placeholder}`` for what an anonymous caller
            may not read.

    Returns:
        A new dict. ``payload`` is not modified.
    """
    redacted = dict(payload)
    for field, placeholder in blanks.items():
        if field in redacted:
            redacted[field] = placeholder
    return redacted
