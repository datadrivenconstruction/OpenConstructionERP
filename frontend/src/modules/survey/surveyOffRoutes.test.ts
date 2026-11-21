import { describe, expect, it } from 'vitest';
import { matchRoutes } from 'react-router-dom';
import { manifest } from './manifest';

describe('survey switched off', () => {
  it('answers every /survey sub-page with the setup card, not 404', () => {
    const routes = (manifest.offRoutes ?? []).map((r) => ({ path: r.path }));
    for (const url of ['/survey', '/survey/plan', '/survey/calc', '/survey/points']) {
      expect(matchRoutes(routes, url), url).not.toBeNull();
    }
  });
});
