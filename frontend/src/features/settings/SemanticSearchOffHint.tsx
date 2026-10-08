// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Semantic search is off until someone turns it on in Settings, so every place
// that would use it says so here, with the way to the switch, instead of
// quietly answering from text search. Renders nothing unless the server
// reports the switch as off; otherwise it renders `children`, so a caller can
// keep its own "not installed" notice for the other states.

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { Info } from 'lucide-react';

import { aiEstimatorApi } from '@/features/ai-estimator/api';

export function useSemanticSearchOff(): boolean {
  const { data } = useQuery({
    queryKey: ['embedding-model-status'],
    queryFn: aiEstimatorApi.embeddingModelStatus,
    retry: false,
    staleTime: 60_000,
  });
  return data?.state === 'disabled';
}

export function SemanticSearchOffHint({
  className,
  children,
}: {
  className?: string;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const off = useSemanticSearchOff();
  if (!off) return <>{children ?? null}</>;
  return (
    <div
      role="status"
      className={clsx(
        'flex items-start gap-2 rounded-lg border border-border bg-surface-secondary px-3 py-2 text-xs text-content-secondary',
        className,
      )}
    >
      <Info size={14} className="mt-0.5 shrink-0 text-oe-blue" />
      <span>
        {t('settings.semantic_off_hint', {
          defaultValue:
            'Semantic search is off, so these are text search results. To search by meaning, turn it on in Settings, AI. It needs about 1 GB of free memory.',
        })}{' '}
        <Link to="/settings?tab=ai" className="font-medium text-oe-blue hover:underline">
          {t('settings.semantic_off_hint_link', { defaultValue: 'Open settings' })}
        </Link>
      </span>
    </div>
  );
}
