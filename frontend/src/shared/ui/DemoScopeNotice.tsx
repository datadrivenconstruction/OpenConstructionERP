// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The line above a list on the hosted demo that says whose data it shows: the
 * open demo's project, or every demo project. One button switches between the
 * two, so the narrowed list is never a silent filter.
 */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Filter } from 'lucide-react';
import type { DemoScope } from '@/shared/lib/useDemoScope';

export function DemoScopeNotice({ scope, className }: { scope: DemoScope; className?: string }) {
  const { t } = useTranslation();
  if (!scope.demoMode || !scope.project) return null;
  const name = scope.project.name;
  const narrowed = scope.projectId !== null;
  return (
    <div
      data-testid="demo-scope-notice"
      data-scope={narrowed ? 'demo' : 'all'}
      className={clsx(
        'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-oe-blue/30 bg-oe-blue/5 px-3 py-2 text-sm text-content-secondary',
        className,
      )}
    >
      <Filter size={14} className="shrink-0 text-oe-blue" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        {narrowed
          ? t('demo_scope.only_project', { defaultValue: 'Showing the {{name}} demo only.', name })
          : t('demo_scope.all_projects', { defaultValue: 'Showing every demo project.' })}
      </span>
      <button
        type="button"
        data-testid="demo-scope-toggle"
        onClick={() => scope.setShowAll(narrowed)}
        className="rounded-md px-2 py-1 font-semibold text-oe-blue hover:bg-oe-blue/10"
      >
        {narrowed
          ? t('demo_scope.show_all', { defaultValue: 'Show all demo projects' })
          : t('demo_scope.only_this', { defaultValue: 'Back to {{name}}', name })}
      </button>
    </div>
  );
}
