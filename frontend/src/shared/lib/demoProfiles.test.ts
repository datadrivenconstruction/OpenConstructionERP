import { afterEach, describe, expect, it } from 'vitest';
import { DEMO_PROFILES, MENU_STYLES, applyDemoMenuStyle, demoProfile } from './demoProfiles';
import { navGroups } from '@/app/layout/navCatalog';

describe('demo profiles', () => {
  afterEach(() => applyDemoMenuStyle(null));

  it('offers five demos, the full platform first', () => {
    expect(DEMO_PROFILES).toHaveLength(5);
    expect(DEMO_PROFILES[0]!.slug).toBe('full-showcase-riyadh');
    expect(DEMO_PROFILES[0]!.groups).toBeNull();
  });

  it('gives every demo its own accent and its own country line', () => {
    const accents = DEMO_PROFILES.map((p) => p.appearance.accent);
    expect(new Set(accents).size).toBe(accents.length);
    const stems = DEMO_PROFILES.map((p) => p.stem);
    expect(new Set(stems).size).toBe(stems.length);
  });

  it('gives every profile its own slug', () => {
    const slugs = DEMO_PROFILES.map((p) => p.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it('gives every profile its own menu style', () => {
    const styles = DEMO_PROFILES.map((p) => p.menuStyle);
    expect(new Set(styles).size).toBe(styles.length);
    styles.forEach((s) => expect(MENU_STYLES).toContain(s));
  });

  it('plays the Berlin contractor on real menu sections with its own look', () => {
    const berlin = demoProfile('residential-berlin');
    expect(berlin?.stem).toBe('demo_profiles.dach_contractor');
    expect(berlin?.appearance.look).toBe('classic');
    expect(berlin?.groups).toContain('grp_procurement');
    const known = new Set(navGroups.map((g) => g.id));
    DEMO_PROFILES.forEach((p) => p.groups?.forEach((g) => expect(known.has(g)).toBe(true)));
  });

  it('sets the menu style on <html> and removes it again', () => {
    applyDemoMenuStyle('dark');
    expect(document.documentElement.dataset.oeMenu).toBe('dark');
    applyDemoMenuStyle(null);
    expect(document.documentElement.dataset.oeMenu).toBeUndefined();
    applyDemoMenuStyle('standard');
    expect(document.documentElement.dataset.oeMenu).toBeUndefined();
  });
});
