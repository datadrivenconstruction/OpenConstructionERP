// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * LinkedPositionsModal — Issue #127 ("utilizar varias veces el mismo Codigo
 * de Seccion, Partida, Recurso").
 *
 * Lists every member of a position's reference-code link group (the master
 * plus its linked instances) and lets the user detach the selected position
 * from the shared code. Read-only otherwise: quantities stay editable in the
 * grid; this modal is purely for visibility + unlink.
 */

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Loader2, Link2, Link2Off, Crown } from 'lucide-react';
import { WideModal } from '@/shared/ui';
import { Button } from '@/shared/ui';
import { boqApi } from './api';
import { fmtWithCurrency } from './boqHelpers';

export interface LinkedPositionsModalProps {
  /** The position whose link group is being inspected. */
  positionId: string;
  /** Ordinal of the inspected position (for the subtitle). */
  positionOrdinal: string;
  locale: string;
  currencyCode: string;
  onClose: () => void;
  /** Detach `positionId` from the shared code (value-preserving). */
  onUnlink: (positionId: string) => void;
  /** Whether an unlink mutation is currently in flight. */
  unlinking: boolean;
}

export function LinkedPositionsModal({
  positionId,
  positionOrdinal,
  locale,
  currencyCode,
  onClose,
  onUnlink,
  unlinking,
}: LinkedPositionsModalProps) {
  const { t } = useTranslation();

  const { data, isLoading, isError } = useQuery({
    queryKey: ['boq-position-links', positionId],
    queryFn: () => boqApi.getPositionLinks(positionId),
    retry: false,
  });

  const handleUnlink = useCallback(() => {
    onUnlink(positionId);
  }, [onUnlink, positionId]);

  const isLinked = !!data?.linked && (data?.total_count ?? 0) > 1;

  const modalTitle = t('boq.linked_positions_title', {
    defaultValue: 'Linked positions',
  });
  const subtitleOpts: Record<string, unknown> = {
    defaultValue: 'Code {{code}} - viewing from position {{ordinal}}',
    code: data?.reference_code ?? positionOrdinal,
    ordinal: positionOrdinal,
  };
  const modalSubtitle = t('boq.linked_positions_subtitle', subtitleOpts);

  return (
    <WideModal
      open
      onClose={onClose}
      size="lg"
      title={modalTitle}
      subtitle={modalSubtitle}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          {isLinked && (
            <Button
              variant="danger"
              onClick={handleUnlink}
              disabled={unlinking}
              icon={
                unlinking ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Link2Off size={14} />
                )
              }
            >
              {t('boq.unlink_this', {
                defaultValue: 'Unlink this position',
              })}
            </Button>
          )}
        </>
      }
    >
      {isLoading && (
        <div className="flex items-center justify-center gap-2 py-12 text-content-tertiary">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">
            {t('common.loading', { defaultValue: 'Loading…' })}
          </span>
        </div>
      )}

      {isError && (
        <div className="py-12 text-center text-sm text-content-tertiary">
          {t('boq.linked_positions_error', {
            defaultValue: 'Could not load linked positions.',
          })}
        </div>
      )}

      {data && !isLoading && (
        <>
          {!isLinked ? (
            <div className="py-10 text-center">
              <Link2Off
                size={28}
                className="mx-auto mb-3 text-content-tertiary/50"
              />
              <p className="text-sm text-content-secondary">
                {t('boq.linked_positions_none', {
                  defaultValue:
                    'This position is standalone - no other position shares its code.',
                })}
              </p>
            </div>
          ) : (
            <>
              <p className="mb-3 text-xs text-content-tertiary">
                {t('boq.linked_positions_count', {
                  defaultValue:
                    '{{total}} positions share this code ({{instances}} linked instance(s)). The master is the definition of record; editing it propagates to every instance in this project.',
                  total: data.total_count,
                  instances: data.instance_count,
                })}
              </p>
              <ul className="divide-y divide-border-light/60 rounded-lg border border-border-light overflow-hidden">
                {data.members.map((m) => (
                  <li
                    key={m.id}
                    className={`flex items-center gap-3 px-3 py-2.5 text-sm ${
                      m.id === positionId
                        ? 'bg-oe-blue/5'
                        : 'bg-surface-elevated'
                    }`}
                  >
                    <span
                      className={`inline-flex h-6 w-6 shrink-0 items-center justify-center rounded ${
                        m.is_master
                          ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                          : 'bg-oe-blue/10 text-oe-blue'
                      }`}
                      title={
                        m.is_master
                          ? t('boq.link_role_master', {
                              defaultValue: 'Master (definition of record)',
                            })
                          : t('boq.link_role_instance', {
                              defaultValue: 'Linked instance',
                            })
                      }
                    >
                      {m.is_master ? (
                        <Crown size={13} />
                      ) : (
                        <Link2 size={13} />
                      )}
                    </span>
                    <span className="w-20 shrink-0 font-mono text-xs text-content-secondary">
                      {m.ordinal}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-content-primary">
                      {m.description ||
                        t('boq.no_description', {
                          defaultValue: '(no description)',
                        })}
                    </span>
                    {m.is_master && (
                      <span className="shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-600 dark:text-amber-400">
                        {t('boq.link_master_badge', {
                          defaultValue: 'Master',
                        })}
                      </span>
                    )}
                    <span className="w-28 shrink-0 text-right tabular-nums text-content-secondary">
                      {fmtWithCurrency(m.total, locale, currencyCode)}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </WideModal>
  );
}
