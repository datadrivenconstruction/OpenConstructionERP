"""Exercise the release guard with the same bash used by GitHub Actions."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which('bash')
if os.name == 'nt':
    git_bash = Path('C:/Program Files/Git/bin/bash.exe')
    BASH = str(git_bash) if git_bash.exists() else BASH


class NotarizationPolicyTests(unittest.TestCase):
    def test_guard_runs_before_the_action_that_uploads_installers(self):
        workflow = (ROOT / '.github/workflows/desktop-release.yml').read_text()
        guard = workflow.index('run: bash desktop/check-macos-notarization-policy.sh')
        upload = workflow.index('uses: tauri-apps/tauri-action@')
        self.assertLess(guard, upload)
        self.assertIn('MACOS_NOTARIZATION_REQUIRED: ${{ vars.MACOS_NOTARIZATION_REQUIRED }}',
                      workflow[:guard])

    def test_unactivated_pipeline_warns_or_refuses_before_publication(self):
        self.assertIsNotNone(BASH, 'Bash is required to exercise the release guard')
        for required, expected in [(None, 0), ('', 0), ('false', 0), ('true', 1),
                                   ('TRUE', 1), ('0', 1), (' false ', 1)]:
            with self.subTest(required=required), tempfile.TemporaryDirectory() as temp:
                env = dict(os.environ,
                           GITHUB_STEP_SUMMARY=str(Path(temp) / 'summary.md'),
                           APPLE_CERTIFICATE='dummy-must-not-be-printed',
                           APPLE_SIGNING_IDENTITY='dummy-must-not-be-printed',
                           APPLE_ID='dummy-must-not-be-printed',
                           APPLE_PASSWORD='dummy-must-not-be-printed',
                           APPLE_API_KEY='dummy-must-not-be-printed')
                env.pop('MACOS_NOTARIZATION_REQUIRED', None)
                if required is not None:
                    env['MACOS_NOTARIZATION_REQUIRED'] = required
                summary = Path(env['GITHUB_STEP_SUMMARY'])
                summary.write_text('Earlier build results\n', encoding='utf-8')
                result = subprocess.run(
                    [BASH, str(ROOT / 'desktop/check-macos-notarization-policy.sh')],
                    env=env, text=True, capture_output=True, check=False, timeout=15)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertIn('::warning' if expected == 0 else '::error', result.stdout)
                report = summary.read_text(encoding='utf-8')
                self.assertNotIn('dummy-must-not-be-printed', result.stdout + result.stderr + report)
                self.assertTrue(report.startswith('Earlier build results\n'))
                self.assertIn('not notarized', report)


if __name__ == '__main__':
    unittest.main()
