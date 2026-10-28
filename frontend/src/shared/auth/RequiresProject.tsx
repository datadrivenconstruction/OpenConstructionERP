// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <RequiresProject> — project-gating wrapper.
 *
 * Renders children only when an active project is selected. Otherwise
 * surfaces a single, consistent EmptyState that points the user to the
 * Projects page. Before this wrapper, ~30 pages reinvented this gate
 * inline with slightly different wording (UX audit blocker).
 *
 * Resolution chain mirrors what every page already did manually:
 *   1. ``:projectId`` route param (when the page is mounted under a
 *      project-scoped route)
 *   2. ``useProjectContextStore`` ``activeProjectId`` (header switcher)
 *
 * Usage:
 *   <RequiresProject>
 *     <MyProjectScopedContent />
 *   </RequiresProject>
 *
 *   // Override the default description (e.g. module-specific hint):
 *   <RequiresProject emptyHint={t('rfi.select_project_hint')}>
 *     ...
 *   </RequiresProject>
 */

import type { ReactNode } from 'react';
import { ArrowUp, FolderOpen } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

export interface RequiresProjectProps {
  children: ReactNode;
  /** Optional override for the description shown in the empty state. */
  emptyHint?: string;
  /** Optional override for the title shown in the empty state. */
  emptyTitle?: string;
}

export function RequiresProject({ children, emptyHint, emptyTitle }: RequiresProjectProps) {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';

  if (projectId) {
    return <>{children}</>;
  }

  const title = emptyTitle ?? t('requiresProject.title', { defaultValue: 'No project selected' });
  const hint =
    emptyHint ??
    t('requiresProject.description', {
      defaultValue:
        'Pick a project from the header to continue, or open the Projects page to create or select one.',
    });

  // The arrow is the whole point of this panel: the switcher is in the header,
  // at the start edge, and a person who has never used the app has no reason to
  // look there. It leans up and towards the start, and mirrors under rtl with
  // the rotation rather than a second icon, so it keeps pointing at the control
  // rather than away from it. Decorative - the sentence beside it says the same
  // thing in words.
  return (
    <div className="flex w-full justify-center px-4 py-10">
      <div className="w-full max-w-xl">
        <div className="mb-3 ms-2 flex" aria-hidden="true">
          {/* The bounce and the tilt have to live on DIFFERENT nodes. Both are
              transforms, and an animated transform replaces a declared one for
              the whole cycle, so `animate-bounce -rotate-45` on one element
              resolves to a pure translate and the arrow points straight up -
              past the header, not at the picker. That is invisible to review
              because both classes are present and spelled correctly. Bounce on
              the wrapper, rotate on the icon, and each keeps its own axis.

              This split is the ONE correct fix for the whole class, not a local
              workaround: any `animate-*` whose keyframes write a property is
              incompatible with a utility declaring that same property on the
              same element. Do not re-solve it per site - reuse this shape. */}
          <span className="flex animate-bounce motion-reduce:animate-none">
            <ArrowUp
              size={30}
              strokeWidth={1.75}
              className="-rotate-45 text-oe-blue rtl:rotate-45"
            />
          </span>
        </div>
        <div className="rounded-2xl border border-border-light bg-surface-primary p-6 shadow-sm sm:p-8">
          <div className="flex items-start gap-4">
            <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
              <FolderOpen size={24} strokeWidth={1.5} />
            </span>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-content-primary">{title}</h2>
              <p className="mt-1.5 text-sm leading-relaxed text-content-secondary">{hint}</p>
              <div className="mt-5">
                <Link
                  to="/projects"
                  className="inline-flex h-10 items-center justify-center rounded-lg bg-oe-blue px-4 text-sm font-medium text-white transition-colors hover:bg-oe-blue/90"
                >
                  {t('requiresProject.cta', { defaultValue: 'Open Projects' })}
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
