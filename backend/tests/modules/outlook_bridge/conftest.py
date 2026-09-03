# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""These tests simulate the original workspace, whose organisation
facts used to be hard-coded and now come from workspace branding /
environment (see app.core.app_branding). Pinning them here keeps every
literal reference assertion (REG-RFI-..., the org name on mail, the
own-domain rule) meaningful without a branding file on disk.

setdefault, not assignment: a caller that deliberately exports its own
value still wins, and tests that probe the DEFAULTS use monkeypatch to
delete these first.
"""

import os
import tempfile

# Isolate the workspace data dir so the org facts below are what the tests
# actually exercise. org_reference_prefix / org_display_name / org_mail_domains
# resolve branding-file > env > neutral, so a real app_branding.json in the
# developer's ~/.openestimate (a configured reference_prefix, org_name or own
# domains) would silently override these pins and make the assertions depend on
# whose machine runs them. Pointing the lookup at an empty dir means no branding
# file is found and the neutral pins are what actually apply.
if "OE_DATA_DIR" not in os.environ:
    os.environ["OE_DATA_DIR"] = tempfile.mkdtemp(prefix="oe-test-datadir-")

os.environ.setdefault("OE_REGISTER_HOUSE", "REG")
os.environ.setdefault("OE_PM_ORG", "Example Projects Pty Ltd")
os.environ.setdefault("OE_OUTLOOK_OWN_DOMAINS", "example.com")
