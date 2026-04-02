import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { FileText, ChevronDown } from 'lucide-react';
import clsx from 'clsx';
import { apiGet } from '@/shared/lib/api';
import { projectsApi } from '@/features/projects/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

interface BOQItem {
  id: string;
  project_id: string;
  name: string;
  status: string;
  created_at: string;
}

interface BOQPickerProps {
  /** Override project ID (otherwise uses global context) */
  projectId?: string | null;
  selectedBoqId?: string | null;
  onSelectProject?: (projectId: string) => void;
  onSelectBoq: (boqId: string) => void;
  /** Show project selector too */
  showProjectSelector?: boolean;
  className?: string;
}

export function BOQPicker({
  projectId: propProjectId,
  selectedBoqId,
  onSelectProject,
  onSelectBoq,
  showProjectSelector = true,
  className,
}: BOQPickerProps) {
  const { t } = useTranslation();
  const contextProjectId = useProjectContextStore((s) => s.activeProjectId);
  const effectiveProjectId = propProjectId ?? contextProjectId;

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    enabled: showProjectSelector,
  });

  const { data: boqs, isLoading: boqsLoading } = useQuery({
    queryKey: ['boqs', effectiveProjectId],
    queryFn: () => apiGet<BOQItem[]>(`/v1/boq/boqs/?project_id=${effectiveProjectId}`),
    enabled: !!effectiveProjectId,
  });

  const activeProjects = useMemo(
    () => (projects ?? []).filter((p) => p.status !== 'archived'),
    [projects],
  );

  return (
    <div className={clsx('flex flex-wrap items-center gap-2', className)}>
      {/* Project selector */}
      {showProjectSelector && (
        <div className="relative">
          <select
            value={effectiveProjectId ?? ''}
            onChange={(e) => onSelectProject?.(e.target.value)}
            className={clsx(
              'h-9 appearance-none rounded-lg border border-border bg-surface-primary',
              'pl-3 pr-8 text-sm text-content-primary',
              'focus:outline-none focus:ring-2 focus:ring-oe-blue/30',
              'min-w-[160px] max-w-[240px]',
            )}
          >
            <option value="">
              {t('common.select_project', { defaultValue: 'Select project...' })}
            </option>
            {activeProjects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <ChevronDown
            size={14}
            className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
        </div>
      )}

      {/* BOQ selector */}
      {effectiveProjectId && (
        <div className="relative">
          <select
            value={selectedBoqId ?? ''}
            onChange={(e) => onSelectBoq(e.target.value)}
            disabled={boqsLoading || !boqs || boqs.length === 0}
            className={clsx(
              'h-9 appearance-none rounded-lg border border-border bg-surface-primary',
              'pl-8 pr-8 text-sm text-content-primary',
              'focus:outline-none focus:ring-2 focus:ring-oe-blue/30',
              'min-w-[160px] max-w-[240px]',
              'disabled:opacity-50 disabled:cursor-not-allowed',
            )}
          >
            <option value="">
              {boqsLoading
                ? t('common.loading', { defaultValue: 'Loading...' })
                : boqs && boqs.length > 0
                  ? t('common.select_boq', { defaultValue: 'Select BOQ...' })
                  : t('boq.no_boqs', { defaultValue: 'No BOQs found' })}
            </option>
            {(boqs ?? []).map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          <FileText
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <ChevronDown
            size={14}
            className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
        </div>
      )}
    </div>
  );
}
