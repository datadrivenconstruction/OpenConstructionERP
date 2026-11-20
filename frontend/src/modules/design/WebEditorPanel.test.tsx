import { describe, expect, it } from 'vitest';
import { EN } from './testStrings';
import { statusLine } from './WebEditorPanel';
import { problemKey, type WebEditorStatus } from './webEditorApi';

const t = (k: string, o?: Record<string, unknown>) =>
  (EN[k] ?? k).replace(/\{\{(\w+)\}\}/g, (_, n: string) => String(o?.[n] ?? ''));

const base = (over: Partial<WebEditorStatus> = {}): WebEditorStatus => ({
  host_bridge: [1],
  installed: null,
  feed: { state: 'available', version: '0.10.0', bytes: 50_000_000, bridge: [1], problem: null },
  signing: { key: true, error: null },
  install: { state: 'idle', version: null, done: 0, total: 0, error: null },
  update_available: true,
  can_install: true,
  can_remove: false,
  ...over,
});

describe('web editor status line', () => {
  it('says nothing when the release can be fetched', () => {
    expect(statusLine(base(), t)).toBeNull();
  });

  it('refuses without a signing key and says so', () => {
    expect(statusLine(base({ signing: { key: false, error: null } }), t)).toBe(EN['design.web_editor.problem.no_key']!);
  });

  it('names a release that needs a newer platform', () => {
    const s = base({ feed: { state: 'available', version: '2.0.0', bridge: [2], problem: 'erp_too_old' } });
    expect(statusLine(s, t)).toBe(EN['design.web_editor.problem.erp_too_old']!);
  });

  it('keeps the engine message when no release is published', () => {
    expect(statusLine(base({ feed: { state: 'absent' } }), t)).toBe(EN['design.web_editor.feed.absent']!);
  });

  it('shows download progress', () => {
    const s = base({ install: { state: 'downloading', version: '0.10.0', done: 1_048_576, total: 2_097_152, error: null } });
    expect(statusLine(s, t)).toMatch(/Downloading/);
  });

  it('maps every server code to a sentence that exists', () => {
    for (const code of ['no_key', 'signature_wrong_key', 'feed_unreachable', 'integrity', 'whatever', null]) {
      expect(EN[problemKey(code)]!).toBeTruthy();
    }
  });
});
