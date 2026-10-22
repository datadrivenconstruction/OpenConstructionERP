// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DemoSwitcherBar - slim tab strip on the public hosted demo that switches
 * between the four showcase projects. Rendered only when the backend reports
 * `demo_mode: true`. Projects are matched by the `demo_id` marker the demo
 * installer writes into project metadata, so no ids are hardcoded.
 *
 * A link from the website may carry `?demo=<slug>`; `captureDemoPick()` runs
 * at boot (before login can drop the query) and the bar applies it once the
 * project list is loaded.
 */

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import { Lock } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

export const DEMO_SWITCHER_SLUGS = [
  'consultancy-riyadh',
  'contractor-jeddah',
  'site-development-dammam',
  'full-showcase-riyadh',
] as const;

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

export function DemoSwitcherBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

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

  const bySlug = new Map<string, DemoProject>();
  for (const p of projects ?? []) {
    const slug = typeof p.metadata?.demo_id === 'string' ? p.metadata.demo_id : '';
    if (slug && !bySlug.has(slug)) bySlug.set(slug, p);
  }

  const open = (p: DemoProject) => {
    setActiveProject(p.id, p.name);
    navigate(`/projects/${p.id}`);
  };

  useEffect(() => {
    if (!projects) return;
    let slug: string | null = null;
    try {
      slug = sessionStorage.getItem(PICK_KEY);
      if (slug) sessionStorage.removeItem(PICK_KEY);
    } catch {
      slug = null;
    }
    const target = slug ? bySlug.get(slug) : undefined;
    if (target) open(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects]);

  if (!demoMode) return null;

  return (
    <nav
      aria-label={t('demo_switcher.label', { defaultValue: 'Demo projects' })}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border-light bg-surface-primary/90 px-4 py-1.5 text-xs backdrop-blur"
    >
      <span className="font-semibold text-content-secondary">
        {t('demo_switcher.label', { defaultValue: 'Demo projects' })}
      </span>
      <div role="tablist" className="flex flex-wrap gap-1">
        {DEMO_SWITCHER_SLUGS.map((slug) => {
          const p = bySlug.get(slug);
          const active = !!p && p.id === activeProjectId;
          return (
            <button
              key={slug}
              type="button"
              role="tab"
              aria-selected={active}
              disabled={!p}
              title={p ? p.name : t('demo_switcher.not_installed', { defaultValue: 'Not installed on this server' })}
              onClick={() => p && open(p)}
              className={clsx(
                'rounded-full px-3 py-1 font-medium transition-colors',
                active
                  ? 'bg-oe-blue text-white'
                  : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
                !p && 'cursor-not-allowed opacity-40',
              )}
            >
              {t(`demo_switcher.tab_${slug.replace(/-/g, '_')}`)}
            </button>
          );
        })}
      </div>
      <span className="ms-auto flex items-center gap-1 text-content-tertiary">
        <Lock size={12} className="shrink-0" />
        {t('demo_switcher.read_only', {
          defaultValue: 'Read-only demo: many functions are limited. Use demo data only, uploads are off.',
        })}
      </span>
    </nav>
  );
}
