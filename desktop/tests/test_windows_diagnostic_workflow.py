"""Exercise diagnostic workflow conditions against release and dispatch contexts."""
import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def condition(expression, *, diagnostic=False, event='workflow_dispatch', tag='', ref='main', title=''):
    value = expression.removeprefix('${{').removesuffix('}}').strip()
    replacements = {
        'inputs.build_only_windows': repr(diagnostic), 'github.event_name': repr(event),
        'inputs.tag': repr(tag), 'github.ref_type': repr('tag' if ref.startswith('v') else 'branch'),
        'github.event.workflow_run.head_branch': repr(ref),
        'github.event.workflow_run.display_title': repr(title),
        'needs.build-tauri.result': repr('success'), 'cancelled()': 'False', 'always()': 'True',
    }
    for key, replacement in replacements.items():
        value = value.replace(key, replacement)
    value = value.replace('&&', ' and ').replace('||', ' or ')
    value = re.sub(r'!(?!=)', 'not ', value)
    return bool(eval(value, {'__builtins__': {}, 'startsWith': lambda text, prefix: text.startswith(prefix)}))


class WindowsDiagnosticWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load((ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8'))
        cls.jobs = cls.workflow['jobs']
        cls.signing = yaml.safe_load((ROOT / '.github/workflows/release-signing.yml').read_text(encoding='utf-8'))

    def test_diagnostic_always_checks_out_the_immutable_run_sha(self):
        self.assertEqual(self.workflow['env']['RELEASE_REF'], '${{ inputs.build_only_windows && github.sha || inputs.tag || github.ref_name }}')
        for name in ('build-sidecar', 'build-tauri'):
            checkout = next(s for s in self.jobs[name]['steps'] if s.get('uses', '').startswith('actions/checkout@'))
            self.assertEqual(checkout['with']['ref'], '${{ env.RELEASE_REF }}')

    def test_diagnostic_matrices_are_windows_only_and_release_matrices_stay_complete(self):
        for name in ('build-sidecar', 'build-tauri'):
            expression = self.jobs[name]['strategy']['matrix']['include']
            choices = re.findall(r"'(\[.*?\])'", expression)
            diagnostic, release = map(json.loads, choices)
            self.assertEqual(diagnostic, [release[0]])
            self.assertEqual(diagnostic[0]['os'], 'windows-latest')
            self.assertEqual({row['os'] for row in release}, {'windows-latest', 'macos-latest', 'ubuntu-22.04'})

    def test_diagnostic_runs_bundler_but_never_publication_jobs_even_with_tag_input(self):
        for tag in ('', 'v18.4.0'):
            self.assertTrue(condition(self.jobs['build-tauri']['if'], diagnostic=True, tag=tag))
            for name in ('build-linux-rpm', 'sign-windows', 'request-signing', 'report'):
                self.assertFalse(condition(self.jobs[name]['if'], diagnostic=True, tag=tag, ref='v18.4.0'), name)
        steps = self.jobs['build-tauri']['steps']
        for name in ('Find the release release.yml published for this tag', 'Build Tauri app'):
            step = next(s for s in steps if s.get('name') == name)
            self.assertFalse(condition(step['if'], diagnostic=True))
        build = next(s for s in steps if s.get('name') == 'Build Windows diagnostic installer without publishing')
        self.assertTrue(condition(build['if'], diagnostic=True))
        self.assertEqual(build['run'], 'npx --yes @tauri-apps/cli@${{ env.TAURI_CLI_VERSION }} build --bundles nsis')
        self.assertNotIn('env', build)

    def test_normal_release_and_sidecar_dispatch_conditions_are_preserved(self):
        for name in ('build-tauri', 'build-linux-rpm'):
            self.assertTrue(condition(self.jobs[name]['if'], event='push', ref='v18.4.0'))
            self.assertTrue(condition(self.jobs[name]['if'], tag='v18.4.0'))
            self.assertFalse(condition(self.jobs[name]['if']))

    def test_completion_cannot_sign_a_release_for_a_diagnostic_run(self):
        self.assertIn("'Windows diagnostic {0}'", self.workflow['run-name'])
        rule = self.signing['jobs']['resolve']['if']
        self.assertFalse(condition(rule, event='workflow_run', ref='v18.4.0', title='Windows diagnostic abcdef'))
        self.assertFalse(condition(rule, event='workflow_run', ref='main'))
        self.assertTrue(condition(rule, event='workflow_run', ref='v18.4.0', title='Desktop Release v18.4.0'))
        self.assertTrue(condition(rule, event='workflow_dispatch', tag='v18.4.0'))

    def test_artifact_has_sha_identity_and_missing_installer_fails(self):
        steps = self.jobs['build-tauri']['steps']
        upload = next(s for s in steps if s.get('name') == 'Upload Windows diagnostic installer')
        self.assertEqual(upload['uses'], 'actions/upload-artifact@v4')
        self.assertIn('windows-diagnostic-${{ github.sha }}', upload['with']['name'])
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        fingerprint = next(s for s in steps if s.get('name') == 'Fingerprint the diagnostic installer and sidecar')
        self.assertIn('Get-FileHash', fingerprint['run'])
        self.assertIn('diagnostic-manifest.json', fingerprint['run'])
        self.assertIn('DIAGNOSTIC_SOURCE_SHA', fingerprint['run'])
        self.assertIn('openconstructionerp-server-x86_64-pc-windows-msvc.exe', fingerprint['run'])


if __name__ == '__main__':
    unittest.main()
