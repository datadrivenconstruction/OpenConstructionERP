import { describe, expect, it } from 'vitest';
import { DEMO_PROFILES, demoProfile } from './demoProfiles';

describe('demo profiles', () => {
  it('offers the Riyadh real estate developer next to the four company types', () => {
    expect(DEMO_PROFILES.map((p) => p.slug)).toContain('residential-riyadh-offplan');
    expect(demoProfile('residential-riyadh-offplan')?.stem).toBe('demo_profiles.developer');
  });

  it('gives every profile its own slug', () => {
    const slugs = DEMO_PROFILES.map((p) => p.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });
});
