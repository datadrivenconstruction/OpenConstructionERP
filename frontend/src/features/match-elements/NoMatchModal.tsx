// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// No-match action modal: Custom position · Send to RFQ · Mark TBD.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { X, FileEdit, Send, Clock, Loader2 } from 'lucide-react';
import { matchElementsApi } from './api';

interface Props {
  sessionId: string;
  groupKey: string;
  onClose: () => void;
  onDone: () => void;
}

type Action = 'custom' | 'rfq' | 'tbd';

export function NoMatchModal({ sessionId, groupKey, onClose, onDone }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [action, setAction] = useState<Action>('tbd');
  const [desc, setDesc] = useState('');
  const [unit, setUnit] = useState('m3');
  const [rate, setRate] = useState('');
  const [saveToCatalogue, setSaveToCatalogue] = useState(false);

  const mut = useMutation({
    mutationFn: () =>
      matchElementsApi.noMatch(sessionId, {
        group_key: groupKey,
        action,
        ...(action === 'custom'
          ? {
              custom_description: desc || undefined,
              custom_unit: unit || undefined,
              custom_rate: rate ? Number(rate) : undefined,
              save_to_my_catalogue: saveToCatalogue,
            }
          : {}),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-detail', sessionId] });
      onDone();
    },
  });

  // Escape closes the modal regardless of which radio is focused.
  // The dialog is always mounted by the parent so this hook always runs.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const opts: Array<{ value: Action; icon: typeof FileEdit; title: string; sub: string }> = [
    {
      value: 'custom',
      icon: FileEdit,
      title: t('match_elements.no_match.custom.title', 'Create custom position'),
      sub: t('match_elements.no_match.custom.sub', 'Add a project-only position with description, unit and rate.'),
    },
    {
      value: 'rfq',
      icon: Send,
      title: t('match_elements.no_match.rfq.title', 'Send to RFQ'),
      sub: t('match_elements.no_match.rfq.sub', 'Mark for tendering - request quotes from subcontractors.'),
    },
    {
      value: 'tbd',
      icon: Clock,
      title: t('match_elements.no_match.tbd.title', 'Mark TBD'),
      sub: t('match_elements.no_match.tbd.sub', 'Park the group; revisit later. Excluded from BOQ totals until resolved.'),
    },
  ];

  return (
    <div
      className="fixed inset-0 bg-black/40 z-popover flex items-center justify-center p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="no-match-modal-heading"
    >
      <div
        className="bg-surface-primary rounded-lg shadow-2xl w-full max-w-lg border border-border-light"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="px-4 py-3 border-b border-border-light flex items-center justify-between">
          <h3 id="no-match-modal-heading" className="text-base font-semibold">
            {t('match_elements.no_match.heading', 'No match - choose action')}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('match_elements.no_match.close', 'Close no-match dialog')}
            className="p-1 rounded hover:bg-surface-secondary"
          >
            <X className="w-5 h-5" />
          </button>
        </header>

        <div className="p-4 space-y-2">
          {opts.map((o) => (
            <label
              key={o.value}
              className={`block p-3 rounded border cursor-pointer transition ${
                action === o.value
                  ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/20'
                  : 'border-border-light hover:border-border'
              }`}
            >
              <div className="flex items-start gap-2">
                <input
                  type="radio"
                  name="no-match-action"
                  value={o.value}
                  checked={action === o.value}
                  onChange={() => setAction(o.value)}
                  className="mt-1"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <o.icon className="w-4 h-4" />
                    {o.title}
                  </div>
                  <div className="text-xs text-content-tertiary mt-0.5">{o.sub}</div>
                </div>
              </div>
            </label>
          ))}

          {action === 'custom' && (
            <div className="border border-border-light rounded p-3 mt-3 space-y-2">
              <input
                type="text"
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
                placeholder={t('match_elements.no_match.placeholder.description', 'Position description')}
                className="w-full oe-input"
              />
              <div className="flex gap-2">
                <input
                  type="text"
                  value={unit}
                  onChange={(e) => setUnit(e.target.value)}
                  placeholder={t('match_elements.no_match.placeholder.unit', 'Unit')}
                  className="w-24 oe-input"
                />
                <input
                  type="number"
                  value={rate}
                  onChange={(e) => setRate(e.target.value)}
                  placeholder={t('match_elements.no_match.placeholder.rate', 'Unit rate')}
                  step="0.01"
                  className="flex-1 oe-input"
                />
              </div>
              <label className="flex items-start gap-2 text-xs text-content-secondary cursor-pointer pt-1">
                <input
                  type="checkbox"
                  checked={saveToCatalogue}
                  onChange={(e) => setSaveToCatalogue(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  {t(
                    'match_elements.no_match.save_to_catalogue',
                    'Save to my catalogue so I can reuse this rate on other projects',
                  )}
                </span>
              </label>
            </div>
          )}
        </div>

        {mut.isError && (
          <div
            className="mx-4 mb-3 -mt-1 rounded border border-semantic-error/30 bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error"
            role="alert"
          >
            {t('match_elements.no_match.error', 'Could not apply: {{error}}', {
              error: String((mut.error as Error | null)?.message ?? mut.error ?? ''),
            })}
          </div>
        )}

        <footer className="px-4 py-3 border-t border-border-light flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded border border-border hover:bg-surface-secondary"
          >
            {t('match_elements.no_match.cancel', 'Cancel')}
          </button>
          <button
            type="button"
            onClick={() => mut.mutate()}
            disabled={mut.isPending}
            className="px-3 py-1.5 text-sm rounded bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50 inline-flex items-center gap-1.5"
          >
            {mut.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            {t('match_elements.no_match.apply', 'Apply')}
          </button>
        </footer>
      </div>
    </div>
  );
}
