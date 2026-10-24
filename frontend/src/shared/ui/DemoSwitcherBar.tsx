// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DemoSwitcherBar - tab strip on the public hosted demo that switches between
 * the four showcase demos. Rendered only when the backend reports
 * `demo_mode: true`. Projects are matched by the `demo_id` marker the demo
 * installer writes into project metadata, so no ids are hardcoded.
 *
 * Each demo is a company type with its own look and a menu cut to its work
 * (`demoProfiles.ts`). After sign-in the visitor first picks one on
 * `/demo/choose`; a `?demo=<slug>` link from the website skips the picker.
 */

import { useCallback, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import { LayoutGrid, Lock } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { ACCENT_SWATCH } from '@/shared/lib/appearance';
import {
  DEMO_PROFILES,
  demoProfile,
  hiddenGroupsFor,
  readChosenDemo,
  writeChosenDemo,
  type DemoSlug,
} from '@/shared/lib/demoProfiles';
import { fetchProjectList } from '@/shared/lib/projectList';
import { navGroups } from '@/app/layout/navCatalog';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

export const DEMO_SWITCHER_SLUGS = DEMO_PROFILES.map((p) => p.slug);

export const DEMO_CHOOSER_PATH = '/demo/choose';

const PICK_KEY = 'oe_demo_pick';

/** Remember a `?demo=<slug>` deep link for after sign-in. */
export function captureDemoPick(search: string = window.location.search): void {
  try {
    const slug = new URLSearchParams(search).get('demo');
    if (slug && (DEMO_SWITCHER_SLUGS as readonly string[]).includes(slug)) {
      sessionStorage.setItem(PICK_KEY, slug);
    }
  } catch {
    // Storage blocked: the deep link is a convenience, the tabs still work.
  }
}

interface DemoProject {
  id: string;
  name: string;
  metadata?: Record<string, unknown> | null;
}

/** Demo mode, the demo projects this account can see, and how to open one. */
export function useDemoProjects() {
  const navigate = useNavigate();
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const setAppearance = useAppearanceStore((s) => s.setAppearance);
  const setHiddenGroups = useModuleStore((s) => s.setHiddenGroups);

  const { data: sys } = useQuery<{ demo_mode?: boolean }>({
    queryKey: ['system-status'],
    queryFn: () => apiGet<{ demo_mode?: boolean }>('/system/status'),
    retry: false,
    staleTime: Infinity,
  });
  const demoMode = sys?.demo_mode === true;

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<DemoProject[]>(),
    staleTime: 60_000,
    enabled: demoMode,
  });

  const bySlug = useMemo(() => {
    const map = new Map<string, DemoProject>();
    for (const p of projects ?? []) {
      const slug = typeof p.metadata?.demo_id === 'string' ? p.metadata.demo_id : '';
      if (slug && !map.has(slug)) map.set(slug, p);
    }
    return map;
  }, [projects]);

  const open = useCallback(
    (slug: DemoSlug) => {
      const p = bySlug.get(slug);
      const profile = demoProfile(slug);
      if (!p || !profile) return;
      setAppearance(profile.appearance);
      setHiddenGroups(
        hiddenGroupsFor(
          profile,
          navGroups.map((g) => g.id),
        ),
      );
      writeChosenDemo(slug);
      setActiveProject(p.id, p.name);
      navigate(`/projects/${p.id}`);
    },
    [bySlug, navigate, setActiveProject, setAppearance, setHiddenGroups],
  );

  return { demoMode, loaded: projects !== undefined, bySlug, open };
}

export function DemoSwitcherBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { demoMode, loaded, bySlug, open } = useDemoProjects();

  useEffect(() => {
    if (!demoMode || !loaded) return;
    let slug: string | null = null;
    try {
      slug = sessionStorage.getItem(PICK_KEY);
      if (slug) sessionStorage.removeItem(PICK_KEY);
    } catch {
      slug = null;
    }
    const picked = demoProfile(slug);
    if (picked && bySlug.has(picked.slug)) {
      open(picked.slug);
      return;
    }
    // First stop after sign-in is the picker, once per browser session.
    if (!readChosenDemo() && pathname !== DEMO_CHOOSER_PATH && bySlug.size > 0) {
      navigate(DEMO_CHOOSER_PATH, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demoMode, loaded]);

  // A tab whose project this account cannot see would only sit there greyed out.
  const available = DEMO_PROFILES.filter((p) => bySlug.has(p.slug));
  if (!demoMode || available.length === 0 || pathname === DEMO_CHOOSER_PATH) return null;

  return (
    <nav
      aria-label={t('demo_switcher.label', { defaultValue: 'Demo projects' })}
      className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border-light bg-surface-primary/90 px-4 py-2 text-sm backdrop-blur"
    >
      <button
        type="button"
        onClick={() => navigate(DEMO_CHOOSER_PATH)}
        className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 font-semibold text-content-secondary hover:bg-surface-secondary hover:text-content-primary"
      >
        <LayoutGrid size={16} className="shrink-0" />
        {t('demo_switcher.label', { defaultValue: 'Demo projects' })}
      </button>
      <div role="tablist" className="flex flex-wrap gap-1.5">
        {available.map((profile) => {
          const p = bySlug.get(profile.slug);
          const active = !!p && p.id === activeProjectId;
          return (
            <button
              key={profile.slug}
              type="button"
              role="tab"
              aria-selected={active}
              title={p?.name}
              onClick={() => open(profile.slug)}
              className={clsx(
                'flex items-center gap-2 rounded-full border px-4 py-1.5 font-medium transition-colors',
                active
                  ? 'border-transparent bg-oe-blue text-white shadow-sm'
                  : 'border-border-light text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
              )}
            >
              <span
                aria-hidden="true"
                className="h-2.5 w-2.5 shrink-0 rounded-full ring-2 ring-white/70"
                style={{ backgroundColor: ACCENT_SWATCH[profile.appearance.accent] }}
              />
              {t(`demo_switcher.tab_${profile.slug.replace(/-/g, '_')}`)}
            </button>
          );
        })}
      </div>
      <span className="ms-auto flex items-center gap-1 text-xs text-content-tertiary">
        <Lock size={12} className="shrink-0" />
        {t('demo_switcher.read_only', {
          defaultValue: 'Read-only demo: many functions are limited. Use demo data only, uploads are off.',
        })}
      </span>
    </nav>
  );
}
