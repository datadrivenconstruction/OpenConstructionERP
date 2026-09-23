// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <BOQListLoadError> - what the bill register shows when its one batched
 * request for every project's bills is refused.
 *
 * The register used to ask once per project and quietly drop any project that
 * failed, so a total across the list could leave a project out and still look
 * complete. The batched call refuses instead, naming the projects it could not
 * read, and this puts those names in front of the reader with a way to retry.
 * Any other failure (network, server, a missing permission) names no project
 * and goes to the shared recovery card, which already knows those cases.
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
          'These projects could not be read: {{projects}}. They may have been archived, deleted or unshared since the page opened. Nothing is listed, so no total leaves them out.',
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
