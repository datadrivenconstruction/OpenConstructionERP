import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const html = readFileSync(path.resolve(__dirname, '../../../index.html'), 'utf-8');

describe('index.html under the /demo sub-path', () => {
  it('prefixes every root-absolute icon, font and manifest link', () => {
    const script = html.match(/<script>\s*\(function \(\) \{\s*var p = location\.pathname;[\s\S]*?<\/script>/);
    expect(script).not.toBeNull();
    const body = script![0];
    const hrefs = [...html.matchAll(/<link[^>]*href="(\/[^"]+)"/g)].map((m) => m[1]);
    const rooted = hrefs.filter((h) => /^\/(favicon|apple-touch|brand\/|assets\/vendor\/)/.test(h));
    expect(rooted.length).toBeGreaterThan(0);
    for (const sel of ['/favicon', '/apple-touch', '/brand/', '/assets/vendor/', 'rel="manifest"']) {
      expect(body).toContain(sel);
    }
    expect(body).toContain("'/demo'");
  });
});
