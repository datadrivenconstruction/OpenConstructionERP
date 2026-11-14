import { afterEach, describe, expect, it } from 'vitest';
import { DEMO_PROFILES, MENU_STYLES, applyDemoMenuStyle, demoModuleRoutes, demoProfile } from './demoProfiles';
import { navGroups } from '@/app/layout/navCatalog';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { useDemoSessionStore } from '@/stores/useDemoSessionStore';

describe('demo profiles', () => {
  afterEach(() => applyDemoMenuStyle(null));

  it('offers the full platform first and six company demos after it', () => {
    expect(DEMO_PROFILES).toHaveLength(7);
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

  it('gives every profile a known menu style, and neighbours different ones', () => {
    const styles = DEMO_PROFILES.map((p) => p.menuStyle);
    styles.forEach((s) => expect(MENU_STYLES).toContain(s));
    styles.slice(1).forEach((s, i) => expect(s).not.toBe(styles[i]));
  });

  it('pairs every demo with a supported UI language, a pack and its standards', () => {
    const codes = new Set(SUPPORTED_LANGUAGES.map((l) => l.code));
    DEMO_PROFILES.forEach((p) => {
      expect(codes.has(p.locale)).toBe(true);
      expect(p.pack).toMatch(/^[a-z0-9-]+$/);
      expect(p.standards.length).toBeGreaterThan(0);
    });
    expect(demoProfile('residential-berlin')?.locale).toBe('de');
    expect(demoProfile('school-paris')?.locale).toBe('fr');
    expect(demoProfile('office-shanghai')?.locale).toBe('zh');
  });

  it('lists the modules a demo covers from its menu sections', () => {
    const full = demoModuleRoutes(demoProfile('full-showcase-riyadh')!, navGroups);
    expect(full).toHaveLength(navGroups.flatMap((g) => g.items).length);
    const shanghai = demoModuleRoutes(demoProfile('office-shanghai')!, navGroups);
    expect(shanghai).toContain('/boq');
    expect(shanghai).toContain('/contracts');
    expect(shanghai).not.toContain('/property-dev');
    expect(shanghai.length).toBeLessThan(full.length);
  });

  it('publishes the active demo and its modules in a store the menu reads', () => {
    useDemoSessionStore.getState().setDemo('school-paris');
    const s = useDemoSessionStore.getState();
    expect(s.slug).toBe('school-paris');
    expect(s.locale).toBe('fr');
    expect(s.groups).toContain('grp_procurement');
    expect(s.modules).toContain('/tendering');
    useDemoSessionStore.getState().setDemo(null);
    expect(useDemoSessionStore.getState()).toMatchObject({ slug: null, groups: null, modules: null });
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
