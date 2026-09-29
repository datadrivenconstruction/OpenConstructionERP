// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What a page or panel shows when the signed-in role cannot read it.
 *
 * Rendered IN PLACE of the content, before any request is made, by callers
 * that already know the answer from `useHasPermission`. It carries the same
 * copy as the 403 branch of `RecoveryCard`, so a role that is turned away up
 * front reads the same words as one turned away by the server.
 */

import { useTranslation } from 'react-i18next';
import { Lock } from 'lucide-react';
import { EmptyState } from './EmptyState';

export function NoAccessState({ className }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <EmptyState
      className={className}
      icon={<Lock size={28} strokeWidth={1.5} />}
      title={t('recovery.no_access_title', { defaultValue: 'You don’t have access here' })}
      description={t('recovery.no_access_desc', {
        defaultValue:
          'Your role is missing the permission needed to view this. Ask a project administrator to grant you access.',
      })}
    />
  );
}
