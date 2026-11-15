import { afterEach, describe, expect, it } from 'vitest';
import { appBasePath, publicAsset } from './publicAsset';

function at(path: string) {
  window.history.replaceState({}, '', path);
}

describe('publicAsset', () => {
  afterEach(() => at('/'));

  it('keeps root paths at the root deployment', () => {
    at('/boq');
    expect(appBasePath()).toBe('');
    expect(publicAsset('/brand/erp/erp-mark-light.svg')).toBe('/brand/erp/erp-mark-light.svg');
    expect(publicAsset('roles/x-96.webp')).toBe('/roles/x-96.webp');
  });

  it('prefixes /demo on the public demo', () => {
    at('/demo/projects');
    expect(publicAsset('/assets/vendor/fonts/inter.css')).toBe('/demo/assets/vendor/fonts/inter.css');
    at('/demo');
    expect(appBasePath()).toBe('/demo');
  });

  it('does not treat /demonstration as the demo', () => {
    at('/demonstration');
    expect(appBasePath()).toBe('');
  });
});
