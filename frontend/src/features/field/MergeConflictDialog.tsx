// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Side-by-side resolution of the edits a version conflict could not settle by​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * itself: a long text both sides changed, and checklist items both sides
 * changed differently. Simple fields never reach this dialog (the local edit,
 * being the last writer, already won).
 *
 * Pure view over `ThreeWayMergeResult.conflicts`; the caller turns the returned
 * decisions into a merge request.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { GitMerge, Loader2 } from 'lucide-react';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import type {
  ChecklistConflict,
  ChecklistItemConflict,
  ConflictDecisions,
  MergeChoice,
  MergeConflict,
  TextConflict,
} from '@/shared/lib/offline/threeWayMerge';

export interface MergeConflictDialogProps {
  open: boolean;
  /** Record label for the heading, e.g. the punch item title. */
  recordLabel?: string;
  conflicts: MergeConflict[];
  busy?: boolean;
  onResolve: (decisions: ConflictDecisions) => void;
  /** Throw away this device's edit and keep the server copy. */
  onKeepTheirs?: () => void;
  onClose: () => void;
}

interface TextPick {
  choice: MergeChoice;
  value: string;
}

function itemText(item: ChecklistItemConflict['mine']): string {
  if (!item) return '';
  const label = item.question ?? item.description ?? item.id;
  return String(label);
}

function itemState(item: ChecklistItemConflict['mine']): string[] {
  if (!item) return [];
  const bits: string[] = [];
  if (typeof item.passed === 'boolean') bits.push(item.passed ? 'passed' : 'failed');
  if (item.critical === true) bits.push('critical');
  if (typeof item.notes === 'string' && item.notes) bits.push(item.notes);
  return bits;
}

export function MergeConflictDialog({
  open,
  recordLabel,
  conflicts,
  busy = false,
  onResolve,
  onKeepTheirs,
  onClose,
}: MergeConflictDialogProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const [text, setText] = useState<Record<string, TextPick>>({});
  const [list, setList] = useState<Record<string, Record<string, 'mine' | 'theirs'>>>({});

  const textConflicts = useMemo(() => conflicts.filter((c): c is TextConflict => c.kind === 'text'), [conflicts]);
  const listConflicts = useMemo(
    () => conflicts.filter((c): c is ChecklistConflict => c.kind === 'checklist'),
    [conflicts],
  );

  // A new conflict set starts with nothing chosen: no silent default.
  useEffect(() => {
    setText({});
    setList({});
  }, [conflicts]);

  useFocusTrap(ref, open);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey, { capture: true });
    return () => document.removeEventListener('keydown', onKey, { capture: true });
  }, [open, onClose]);

  if (!open) return null;

  const allTextDecided = textConflicts.every((c) => text[c.field]);
  const allListDecided = listConflicts.every((c) => c.items.every((i) => list[c.field]?.[i.id]));
  const complete = allTextDecided && allListDecided;

  const pickText = (c: TextConflict, choice: MergeChoice) => {
    setText((prev) => ({
      ...prev,
      [c.field]: {
        choice,
        value: choice === 'theirs' ? c.theirs : choice === 'mine' ? c.mine : (prev[c.field]?.value ?? c.mine),
      },
    }));
  };

  const submit = () => {
    const decisions: ConflictDecisions = { text: {}, checklist: {} };
    for (const c of textConflicts) {
      const p = text[c.field];
      if (p) decisions.text![c.field] = { choice: p.choice, value: p.value };
    }
    for (const c of listConflicts) decisions.checklist![c.field] = { ...(list[c.field] ?? {}) };
    onResolve(decisions);
  };

  const sideCls = (active: boolean) =>
    `rounded-lg border p-3 text-sm text-left min-h-[44px] ${
      active ? 'border-oe-blue bg-oe-blue/10' : 'border-border bg-surface-primary'
    }`;

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg" />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={t('offline_sync.merge_title', { defaultValue: 'Merge your changes' })}
        data-testid="merge-conflict-dialog"
        tabIndex={-1}
        className="relative z-10 flex max-h-[92vh] w-full max-w-3xl flex-col rounded-t-2xl sm:rounded-2xl border border-border-light bg-surface-elevated shadow-xl"
      >
        <div className="flex items-start gap-3 px-4 pt-4 pb-2 sm:px-6">
          <GitMerge size={20} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden="true" />
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-content-primary">
              {t('offline_sync.merge_title', { defaultValue: 'Merge your changes' })}
            </h2>
            <p className="mt-1 text-sm text-content-secondary">
              {t('offline_sync.merge_intro', {
                defaultValue:
                  'Someone changed this record while you were offline. Choose what to keep for the fields below. Everything else already merged.',
              })}
            </p>
            {recordLabel && <p className="mt-1 truncate text-xs text-content-tertiary">{recordLabel}</p>}
          </div>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-4 py-3 sm:px-6">
          {textConflicts.map((c) => {
            const pick = text[c.field];
            return (
              <section key={c.field} data-testid={`merge-text-${c.field}`} className="space-y-2">
                <h3 className="text-sm font-semibold text-content-primary">
                  {t(`offline_sync.field_${c.field}`, { defaultValue: c.field.replace(/_/g, ' ') })}
                </h3>
                <div className="grid gap-2 sm:grid-cols-2">
                  <button
                    type="button"
                    data-testid={`merge-mine-${c.field}`}
                    aria-pressed={pick?.choice === 'mine'}
                    onClick={() => pickText(c, 'mine')}
                    className={sideCls(pick?.choice === 'mine')}
                  >
                    <span className="mb-1 block text-xs font-semibold uppercase text-content-tertiary">
                      {t('offline_sync.mine', { defaultValue: 'Mine (this device)' })}
                    </span>
                    <span className="whitespace-pre-wrap break-words">{c.mine || ' '}</span>
                  </button>
                  <button
                    type="button"
                    data-testid={`merge-theirs-${c.field}`}
                    aria-pressed={pick?.choice === 'theirs'}
                    onClick={() => pickText(c, 'theirs')}
                    className={sideCls(pick?.choice === 'theirs')}
                  >
                    <span className="mb-1 block text-xs font-semibold uppercase text-content-tertiary">
                      {t('offline_sync.theirs', { defaultValue: 'Theirs (server)' })}
                    </span>
                    <span className="whitespace-pre-wrap break-words">{c.theirs || ' '}</span>
                  </button>
                </div>
                <label className="block text-xs font-medium text-content-secondary">
                  {t('offline_sync.merged_text', { defaultValue: 'Or write the merged text' })}
                  <textarea
                    data-testid={`merge-manual-${c.field}`}
                    value={pick?.choice === 'manual' ? pick.value : ''}
                    placeholder={t('offline_sync.merged_text_placeholder', {
                      defaultValue: 'Combine both versions here',
                    })}
                    onFocus={() => {
                      if (pick?.choice !== 'manual') {
                        setText((prev) => ({
                          ...prev,
                          [c.field]: { choice: 'manual', value: prev[c.field]?.value ?? c.mine },
                        }));
                      }
                    }}
                    onChange={(e) =>
                      setText((prev) => ({ ...prev, [c.field]: { choice: 'manual', value: e.target.value } }))
                    }
                    rows={4}
                    className="mt-1 w-full rounded-lg border border-border bg-surface-primary p-2 text-sm text-content-primary"
                  />
                </label>
              </section>
            );
          })}

          {listConflicts.map((c) => (
            <section key={c.field} data-testid={`merge-list-${c.field}`} className="space-y-2">
              <h3 className="text-sm font-semibold text-content-primary">
                {t(`offline_sync.field_${c.field}`, { defaultValue: c.field.replace(/_/g, ' ') })}
              </h3>
              {c.items.map((item) => {
                const side = list[c.field]?.[item.id];
                const choose = (s: 'mine' | 'theirs') =>
                  setList((prev) => ({ ...prev, [c.field]: { ...(prev[c.field] ?? {}), [item.id]: s } }));
                const render = (v: ChecklistItemConflict['mine']) =>
                  v ? (
                    <>
                      <span className="block break-words">{itemText(v)}</span>
                      {itemState(v).length > 0 && (
                        <span className="block text-xs text-content-tertiary">{itemState(v).join(' · ')}</span>
                      )}
                    </>
                  ) : (
                    <span className="italic text-content-tertiary">
                      {t('offline_sync.item_removed', { defaultValue: 'Removed' })}
                    </span>
                  );
                return (
                  <div key={item.id} className="grid gap-2 sm:grid-cols-2" data-testid={`merge-item-${item.id}`}>
                    <button
                      type="button"
                      data-testid={`merge-item-mine-${item.id}`}
                      aria-pressed={side === 'mine'}
                      onClick={() => choose('mine')}
                      className={sideCls(side === 'mine')}
                    >
                      <span className="mb-1 block text-xs font-semibold uppercase text-content-tertiary">
                        {t('offline_sync.mine', { defaultValue: 'Mine (this device)' })}
                      </span>
                      {render(item.mine)}
                    </button>
                    <button
                      type="button"
                      data-testid={`merge-item-theirs-${item.id}`}
                      aria-pressed={side === 'theirs'}
                      onClick={() => choose('theirs')}
                      className={sideCls(side === 'theirs')}
                    >
                      <span className="mb-1 block text-xs font-semibold uppercase text-content-tertiary">
                        {t('offline_sync.theirs', { defaultValue: 'Theirs (server)' })}
                      </span>
                      {render(item.theirs)}
                    </button>
                  </div>
                );
              })}
            </section>
          ))}
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-border-light px-4 py-3 sm:flex-row sm:justify-end sm:px-6">
          {onKeepTheirs && (
            <button
              type="button"
              data-testid="merge-keep-theirs"
              onClick={onKeepTheirs}
              disabled={busy}
              className="min-h-[44px] rounded-lg border border-border px-4 text-sm font-medium text-content-primary disabled:opacity-40"
            >
              {t('offline_sync.keep_theirs', { defaultValue: 'Discard my changes' })}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="min-h-[44px] rounded-lg border border-border px-4 text-sm font-medium text-content-primary disabled:opacity-40"
          >
            {t('offline_sync.decide_later', { defaultValue: 'Decide later' })}
          </button>
          <button
            type="button"
            data-testid="merge-apply"
            onClick={submit}
            disabled={!complete || busy}
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-oe-blue px-4 text-sm font-semibold text-white disabled:opacity-40"
          >
            {busy && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            {t('offline_sync.apply_merge', { defaultValue: 'Apply merge' })}
          </button>
        </div>
      </div>
    </div>
  );
}

export default MergeConflictDialog;
