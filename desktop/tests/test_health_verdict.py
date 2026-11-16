# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The release gate must judge /api/health the way the launcher does.

The serve check used to accept any HTTP 200. The backend answers 200 with
``"status": "degraded"`` when its database is down or its UI files are missing,
and the launcher refuses exactly that body (``blocking_fault`` in
desktop/src-tauri/src/main.rs), so a build could pass the gate and still stop
on every user's splash.
"""

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("health_verdict", ROOT / "health_verdict.py")
hv = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hv)


class HealthVerdictTests(unittest.TestCase):
    def test_healthy_body_is_ready(self):
        self.assertEqual(hv.verdict('{"status": "healthy", "database": "ok"}'), None)

    def test_degraded_database_is_refused(self):
        reason = hv.verdict('{"status": "degraded", "database": "error"}')
        self.assertIn("database", reason)

    def test_missing_ui_files_are_refused(self):
        reason = hv.verdict('{"status": "degraded", "database": "ok", "frontend_dist_present": false}')
        self.assertIn("application files", reason)

    def test_degraded_for_another_reason_still_opens(self):
        # The launcher opens a degraded app whose database and UI are fine.
        self.assertEqual(hv.verdict('{"status": "degraded", "database": "ok"}'), None)

    def test_unparseable_body_opens_like_the_launcher(self):
        self.assertEqual(hv.verdict("<html>ok</html>"), None)

    def test_the_launcher_still_uses_the_same_fields(self):
        """Drift guard: if blocking_fault changes its fields, this mirror must follow."""
        source = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        body = re.search(r"fn blocking_fault\(.*?\n}\n", source.replace("\r\n", "\n"), re.S)
        self.assertIsNotNone(body, "blocking_fault not found in main.rs")
        fields = set(re.findall(r'\.get\("([a-z_]+)"\)', body.group(0)))
        self.assertEqual(fields, set(hv.LAUNCHER_FIELDS))


if __name__ == "__main__":
    unittest.main()
