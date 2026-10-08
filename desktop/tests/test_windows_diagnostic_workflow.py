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
        self.assertIn('binaries/server/openconstructionerp-server.exe', fingerprint['run'])

    def test_only_diagnostic_reuses_the_tested_frontend_without_rebuilding(self):
        sidecar = self.jobs['build-sidecar']['steps']
        desktop = self.jobs['build-tauri']['steps']
        source_build = next(s for s in sidecar if s.get('name') == 'Build frontend')
        self.assertNotIn('if', source_build)
        target_build = next(s for s in desktop if s.get('name') == 'Build frontend')
        self.assertFalse(condition(target_build['if'], diagnostic=True))
        self.assertTrue(condition(target_build['if'], event='push', ref='v18.4.0'))
        names = [s.get('name') for s in desktop]
        for name in ('Set up Python for diagnostic frontend verification',
                     'Download diagnostic sidecar before frontend verification',
                     'Download the tested diagnostic frontend',
                     'Verify and restore the tested diagnostic frontend'):
            step = next(s for s in desktop if s.get('name') == name)
            self.assertTrue(condition(step['if'], diagnostic=True))
            self.assertFalse(condition(step['if']))
        normal_sidecar = next(s for s in desktop if s.get('name') == 'Download sidecar')
        self.assertTrue(condition(normal_sidecar['if']))
        self.assertFalse(condition(normal_sidecar['if'], diagnostic=True))
        self.assertEqual(normal_sidecar['with']['name'], 'sidecar-${{ matrix.target }}')
        sidecar_upload = next(s for s in sidecar if s.get('name') == 'Upload sidecar artifact')
        diagnostic_sidecar = next(s for s in desktop if s.get('name') == 'Download diagnostic sidecar before frontend verification')
        self.assertEqual(sidecar_upload['with']['name'], "${{ inputs.build_only_windows && format('sidecar-{0}-{1}-{2}', matrix.target, github.sha, github.run_attempt) || format('sidecar-{0}', matrix.target) }}")
        self.assertEqual(diagnostic_sidecar['with']['name'], 'sidecar-${{ matrix.target }}-${{ github.sha }}-${{ github.run_attempt }}')
        self.assertNotIn('overwrite', sidecar_upload['with'])
        self.assertLess(names.index('Download diagnostic sidecar before frontend verification'),
                        names.index('Verify and restore the tested diagnostic frontend'))
        self.assertLess(names.index('Verify and restore the tested diagnostic frontend'),
                        names.index('Check the frontend build carries the splash screen'))
        self.assertLess(names.index('Check the frontend build carries the splash screen'),
                        names.index('Build Windows diagnostic installer without publishing'))
        upload = next(s for s in sidecar if s.get('name') == 'Upload the tested diagnostic frontend')
        download = next(s for s in desktop if s.get('name') == 'Download the tested diagnostic frontend')
        self.assertEqual(upload['with']['name'], 'frontend-windows-${{ github.sha }}-${{ github.run_attempt }}')
        self.assertEqual(upload['with']['name'], download['with']['name'])
        self.assertNotIn('run-id', download['with'])  # Never consume a different run's build.
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        for steps, name in ((sidecar, 'Package the tested diagnostic frontend'),
                            (desktop, 'Verify and restore the tested diagnostic frontend')):
            step = next(s for s in steps if s.get('name') == name)
            self.assertTrue(condition(step['if'], diagnostic=True))
            self.assertFalse(condition(step['if']))
            for token in ('git rev-parse HEAD', '--source-sha', '--run-id', '--run-attempt', '--sidecar'):
                self.assertIn(token, step['run'])
        source_names = [s.get('name') for s in sidecar]
        self.assertLess(source_names.index('Check the sidecar serves an answer on a cold start and a restart'),
                        source_names.index('Package the tested diagnostic frontend'))
        config = json.loads((ROOT / 'desktop/src-tauri/tauri.conf.json').read_text(encoding='utf-8'))
        self.assertEqual(config['build']['beforeBuildCommand'], '')


if __name__ == '__main__':
    unittest.main()
