import { describe, expect, it } from 'vitest';
import { hostedSrc, parseGuestMessage, type RuntimeUiEntry } from '../runtimeModules';

const entry: RuntimeUiEntry = {
  module: 'oe_demo',
  label: 'Demo',
  group: 'grp_estimating',
  icon: 'package',
  mode: 'hosted',
  path: '/api/v1/demo/ui/',
  project_param: 'project_id',
};

describe('hosted module bridge', () => {
  it('accepts only known guest messages', () => {
    expect(parseGuestMessage({ oe: 'ready' })).toEqual({ oe: 'ready' });
    expect(parseGuestMessage({ oe: 'token' })).toEqual({ oe: 'token' });
    expect(parseGuestMessage({ oe: 'context', token: 'x' })).toBeNull();
    expect(parseGuestMessage('ready')).toBeNull();
    expect(parseGuestMessage(null)).toBeNull();
  });

  it('lets a page navigate only inside the app', () => {
    expect(parseGuestMessage({ oe: 'navigate', to: '/projects' })).toEqual({ oe: 'navigate', to: '/projects' });
    for (const to of ['https://evil.example', '//evil.example', '/\\evil.example', '/evil\\path', 'javascript:alert(1)']) {
      expect(parseGuestMessage({ oe: 'navigate', to })).toBeNull();
    }
  });

  it('passes the active project only when the module asked for it', () => {
    expect(hostedSrc(entry, 'p 1')).toBe('/api/v1/demo/ui/?project_id=p%201');
    expect(hostedSrc(entry, null)).toBe('/api/v1/demo/ui/');
    expect(hostedSrc({ ...entry, project_param: null }, 'p1')).toBe('/api/v1/demo/ui/');
  });
});
