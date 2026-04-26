"""Regression tests for XML XXE / billion-laughs hardening on the schedule
import path.

The schedule router accepts user-uploaded MS Project XML schedules and used
to feed them straight into stdlib ``xml.etree.ElementTree``. That parser is
vulnerable to entity-expansion ("billion laughs") and external-entity
(XXE) attacks. We migrated the parse call to ``defusedxml.ElementTree``
(see app/modules/schedule/router.py:1506).

These tests pin that behaviour: feeding a billion-laughs payload to the
parser used by the import endpoint must raise an EntitiesForbidden-style
exception immediately, *not* expand into gigabytes of memory.

If anyone reverts the parser back to stdlib ``ET.fromstring``, these
tests fail loudly.
"""

from __future__ import annotations

import pytest
from defusedxml import EntitiesForbidden
from defusedxml.common import DefusedXmlException

# This is the exact alias used by the schedule router for parsing.
# Importing it from the router module guarantees the test fails if the
# router is rewritten to bypass defusedxml.
from app.modules.schedule.router import safe_ET


# Classic billion-laughs payload — defines a chain of entities each
# referencing the previous one ten times. A vulnerable parser would
# expand `&lol9;` into 10**9 `lol` strings (~3 GB) and either OOM the
# server or hang for minutes. defusedxml refuses outright.
BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
  <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
  <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
  <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
  <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
  <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
]>
<lolz>&lol9;</lolz>"""


# External-entity payload pointing at a local file. A vulnerable parser
# would try to fetch /etc/passwd; defusedxml raises ExternalReferenceForbidden
# (a DefusedXmlException subclass).
XXE_EXTERNAL = """<?xml version="1.0"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<foo>&xxe;</foo>"""


def test_billion_laughs_is_rejected() -> None:
    """defusedxml must reject entity-bomb payloads outright."""
    with pytest.raises(EntitiesForbidden):
        safe_ET.fromstring(BILLION_LAUGHS)


def test_external_entity_is_rejected() -> None:
    """defusedxml must refuse external-entity references."""
    with pytest.raises(DefusedXmlException):
        safe_ET.fromstring(XXE_EXTERNAL)


def test_benign_xml_still_parses() -> None:
    """Sanity check — defusedxml is a drop-in for legitimate XML."""
    xml = "<schedule><task id='1'>Foundation</task></schedule>"
    root = safe_ET.fromstring(xml)
    assert root.tag == "schedule"
    task = root.find("task")
    assert task is not None
    assert task.text == "Foundation"
    assert task.attrib["id"] == "1"
