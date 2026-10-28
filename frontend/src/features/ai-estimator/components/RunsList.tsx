// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The runs landing list. Recent AI estimate runs for the project plus a
// prominent "New estimate" action. Empty state onboards first-time users.

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Wand2, Plus, ArrowRight, AlertTriangle, RefreshCw } from 'lucide-react';
import { Button, Card, EmptyState, DateDisplay } from '@/shared/ui';
import { fmtMoneyStr, runStatusChip } from '../helpers';
import { STAGES } from './StageRail';
import type { RunSummary } from '../api';

export interface RunsListProps {
  runs: RunSummary[];
  loading: boolean;
  error?: string | null;
  onRetry?: () => void;
  locale?: string;
  onNew: () => void;
  onOpen: (runId: string) => void;
}

export function RunsList({ runs, loading, error, onRetry, locale, onNew, onOpen }: RunsListProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-content-primary">
          {t('aiest.runs.title', { defaultValue: 'Your AI estimates' })}
        </h2>
        <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={onNew}>
          {t('aiest.runs.new', { defaultValue: 'New estimate' })}
        </Button>
      </div>

      {loading ? (
        <div className="space-y-2.5">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-16 animate-pulse rounded-lg border border-border-light bg-surface-secondary"
            />
          ))}
        </div>
      ) : error ? (
        <Card padding="md" className="border-rose-200 dark:border-rose-900/50">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-500" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-content-primary">
                {t('aiest.runs.load_error', { defaultValue: 'Could not load your estimates' })}
              </div>
              <p className="mt-0.5 break-words text-xs text-content-tertiary">{error}</p>
              {onRetry && (
                <Button
                  variant="secondary"
                  size="sm"
                  className="mt-3"
                  icon={<RefreshCw className="h-3.5 w-3.5" />}
                  onClick={onRetry}
                >
                  {t('common.retry', { defaultValue: 'Retry' })}
                </Button>
              )}
            </div>
          </div>
        </Card>
      ) : runs.length === 0 ? (
        <EmptyState
          icon={<Wand2 className="h-6 w-6" />}
          title={t('aiest.runs.empty_title', { defaultValue: 'No AI estimates yet' })}
          description={t('aiest.runs.empty_desc', {
            defaultValue:
              'Start one from any source. The agent reads your data, groups quantities, finds exact catalogue rates and assembles a validated estimate you confirm.',
          })}
          action={{
            label: t('aiest.runs.start_first', { defaultValue: 'Start your first estimate' }),
            onClick: onNew,
          }}
        />
      ) : (
        <div className="space-y-2.5">
          {runs.map((r) => {
            const stage = STAGES.find((s) => s.id === r.current_stage);
            return (
              <Card key={r.id} padding="sm" hoverable className="cursor-pointer">
                <button
                  type="button"
                  onClick={() => onOpen(r.id)}
                  className="flex w-full items-center gap-3 text-left"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
                    <Wand2 className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-content-primary">
                      {r.name ||
                        t('aiest.runs.untitled', { defaultValue: 'Untitled estimate' })}
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-content-tertiary">
                      <DateDisplay value={r.created_at} format="relative" />
                      {stage && (
                        <span>
                          ·{' '}
                          {t(stage.titleKey, { defaultValue: stage.titleFallback })}
                        </span>
                      )}
                      {r.grand_total != null && (
                        <span>· {fmtMoneyStr(r.grand_total, r.currency, locale)}</span>
                      )}
                    </div>
                  </div>
                  <span
                    className={clsx(
                      'shrink-0 rounded-full px-2 py-0.5 text-xs',
                      runStatusChip(r.status),
                    )}
                  >
                    {t(`aiest.status.run_${r.status}`, { defaultValue: r.status })}
                  </span>
                  <ArrowRight className="h-4 w-4 shrink-0 text-content-tertiary" />
                </button>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
