// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <BOQListLoadError> - what the bill register shows when its one batched
 * request for every project's bills is refused, and <BOQListSkippedNotice> -
 * what it shows above the list when the answer left projects out.
 *
 * The register used to ask once per project and quietly drop any project that
 * failed, so a total across the list could leave a project out and still look
 * complete. The batched call now leaves out a project archived or unshared
 * since the page loaded, and the page names it above the totals. An id that
 * names no project at all still refuses the whole call, and this puts those
 * names in front of the reader with a way to retry. Any other failure
 * (network, server, a missing permission) names no project and goes to the
 * shared recovery card, which already knows those cases.
 */

import { useTranslation } from 'react-i18next';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button, EmptyState, RecoveryCard } from '@/shared/ui';
import { fmtList } from '@/shared/lib/formatters';
import { failedBoqListProjectIds } from './api';

export interface BOQListLoadErrorProps {
  /** The error the batched register request was refused with. */
  error: unknown;
  /** The projects the page asked about, to turn failing ids into names. */
  projects: ReadonlyArray<{ id: string; name: string }> | undefined;
  /** Reload the project list and then the bills. */
  onRetry: () => void;
}

export function BOQListLoadError({ error, projects, onRetry }: BOQListLoadErrorProps) {
  const { t } = useTranslation();
  const failed = failedBoqListProjectIds(error);

  if (failed.length === 0) {
    return <RecoveryCard error={error} onRetry={onRetry} />;
  }

  const names = failed.map((id) => projects?.find((p) => p.id === id)?.name || id);
  return (
    <EmptyState
      icon={<AlertTriangle size={28} strokeWidth={1.5} />}
      title={t('boq.list_load_failed_title', { defaultValue: 'Estimates could not be loaded' })}
      description={t('boq.list_load_failed_projects', {
        defaultValue:
          'These projects could not be read: {{projects}}. They may have been archived or deleted, or your access removed, since this page opened. Nothing is listed, so that no total leaves them out.',
        projects: fmtList(names),
      })}
      action={
        <Button variant="secondary" onClick={onRetry} icon={<RefreshCw size={14} />}>
          {t('common.retry', { defaultValue: 'Retry' })}
        </Button>
      }
    />
  );
}

export interface BOQListSkippedNoticeProps {
  /** The projects the answer left out, with the names the page knows them by. */
  projects: ReadonlyArray<{ id: string; name: string }>;
  /** Reload the project list and then the bills. */
  onRefresh: () => void;
}

export function BOQListSkippedNotice({ projects, onRefresh }: BOQListSkippedNoticeProps) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-semantic-warning/30 bg-semantic-warning-bg px-3.5 py-2.5 text-xs text-content-secondary"
    >
      <AlertTriangle size={14} className="shrink-0 text-semantic-warning" aria-hidden />
      <span className="min-w-0 flex-1">
        {t('boq.list_projects_skipped', {
          defaultValue:
            'Not included: {{projects}}. These projects were archived or are no longer shared with you, so the estimates and totals here leave them out.',
          projects: fmtList(projects.map((p) => p.name)),
        })}
      </span>
      <Button variant="ghost" size="sm" onClick={onRefresh} icon={<RefreshCw size={14} />}>
        {t('common.refresh', { defaultValue: 'Refresh' })}
      </Button>
    </div>
  );
}
