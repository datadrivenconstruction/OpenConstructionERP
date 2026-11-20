import { describe, expect, it } from 'vitest';
import { sameOrigin } from './geoOrigin';

describe('map assets through the page origin', () => {
  it('a geo-hub URL naming the backend host is asked from the page origin; others stay', () => {
    expect(sameOrigin('http://127.0.0.1:8123/api/v1/geo-hub/sprite/ofm.json', 'http://127.0.0.1:5173'))
      .toBe('http://127.0.0.1:5173/api/v1/geo-hub/sprite/ofm.json');
    expect(sameOrigin('/api/v1/geo-hub/basemap-style/liberty.json', 'http://x')).toBe('/api/v1/geo-hub/basemap-style/liberty.json');
    expect(sameOrigin('https://tiles.example.org/a.pbf', 'http://x')).toBe('https://tiles.example.org/a.pbf');
  });
});
