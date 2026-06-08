// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Compare-all-candidates drawer. Shows every grounded candidate the
// retriever returned for one group, each with its score, code, rate and
// currency, and lets the human pick a different one. The chosen candidate
// is highlighted. Overriding only ever selects a real returned candidate
// id - the contract forbids fabricated codes, so there is no free-text
// rate entry here. Keyboard: arrow keys move between candidates.

import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { Loader2, Check, CheckCircle2 } from 'lucide-react';
import { Button, SideDrawer } from '@/shared/ui';
import { scoreColor, scorePercent, bandTone, fmtMoneyStr } from '../helpers';
import { useScoreThresholds } from '../meta';
import { aiEstimatorApi, type CandidateOut } from '../api';

export function AlternativesDrawer({
  runId,
  groupId,
  locale,
  open,
  onClose,
  onUse,
}: {
  runId: string;
  groupId: string;
  locale?: string;
  open: boolean;
  onClose: () => void;
  onUse: (candidateId: string | null) => void;
}) {
  const { t } = useTranslation();
  const thresholds = useScoreThresholds();
  const listRef = useRef<HTMLUListElement>(null);

  const detailQ = useQuery({
    enabled: open && !!groupId,
    queryKey: ['aiest-group-detail', runId, groupId],
    queryFn: () => aiEstimatorApi.getGroup(runId, groupId),
  });
  const detail = detailQ.data;
  const candidates = detail?.candidates ?? [];
  const chosenCode = detail?.chosen_code ?? null;

  const onKeyDown = (e: React.KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const items = Array.from(
      listRef.current?.querySelectorAll<HTMLElement>('[data-candidate]') ?? [],
    );
    if (items.length === 0) return;
    const idx = items.findIndex((el) => el === document.activeElement);
    e.preventDefault();
    const next = e.key === 'ArrowDown' ? Math.min(idx + 1, items.length - 1) : Math.max(idx - 1, 0);
    items[next < 0 ? 0 : next]?.focus();
  };

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      widthClass="max-w-lg"
      title={t('aiest.alts.title', { defaultValue: 'Compare catalogue rates' })}
      subtitle={detail?.description ?? detail?.group_key}
    >
      <div className="p-4">
        {detailQ.isLoading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-content-tertiary">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('aiest.alts.loading', { defaultValue: 'Loading candidates...' })}
          </div>
        ) : candidates.length === 0 ? (
          <p className="py-12 text-center text-sm text-content-tertiary">
            {t('aiest.alts.empty', {
              defaultValue:
                'No grounded candidates were returned for this group. Try re-querying with a clearer description.',
            })}
          </p>
        ) : (
          <ul
            ref={listRef}
            onKeyDown={onKeyDown}
            className="space-y-2"
            aria-label={t('aiest.alts.list', { defaultValue: 'Candidate rates' })}
          >
            {candidates.map((c: CandidateOut, i) => {
              const isChosen = c.code === chosenCode;
              return (
                <li
                  key={c.candidate_id ?? `${c.code}-${i}`}
                  data-candidate
                  tabIndex={0}
                  className={clsx(
                    'rounded-lg border px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
                    isChosen
                      ? 'border-emerald-300 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-900/10'
                      : 'border-border-light',
                  )}
                >
                  <div className="flex items-start gap-2.5">
                    <span
                      className={clsx(
                        'mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold',
                        scoreColor(c.score, thresholds),
                      )}
                    >
                      {scorePercent(c.score)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-sm font-medium text-content-primary">
                          {c.description}
                        </span>
                        {isChosen && (
                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                        )}
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-content-tertiary">
                        <span className="font-mono">{c.code}</span>
                        {c.unit_rate != null && Number(c.unit_rate) > 0 ? (
                          <span>
                            {fmtMoneyStr(c.unit_rate, c.currency, locale)} / {c.unit}
                          </span>
                        ) : (
                          <span className="text-amber-600 dark:text-amber-400">
                            {t('aiest.match.no_price', {
                              defaultValue: 'matched, no price in catalogue',
                            })}
                          </span>
                        )}
                        <span className={clsx('font-medium', bandTone(c.confidence_band))}>
                          {t(`aiest.band.${c.confidence_band}`, { defaultValue: c.confidence_band })}
                        </span>
                      </div>
                    </div>
                    <Button
                      variant={isChosen ? 'secondary' : 'primary'}
                      size="sm"
                      icon={<Check className="h-3.5 w-3.5" />}
                      disabled={isChosen}
                      onClick={() => onUse(c.candidate_id)}
                    >
                      {isChosen
                        ? t('aiest.alts.current', { defaultValue: 'Current' })
                        : t('aiest.alts.use', { defaultValue: 'Use this' })}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        <p className="mt-4 text-[11px] text-content-tertiary">
          {t('aiest.alts.grounded_note', {
            defaultValue:
              'Every option is a real catalogue rate. The AI orders the shortlist but never invents a code or a price.',
          })}
        </p>
      </div>
    </SideDrawer>
  );
}
