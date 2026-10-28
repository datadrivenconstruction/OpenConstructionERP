// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <CostCodeAssist> - AI-augmented, human-confirmed cost-code picker.
 *
 * The user types (or reuses) a short description of the work, asks for
 * ranked cost-code suggestions, and CLICKS one to apply it. Nothing is
 * ever applied automatically - the platform rule is "AI proposes, human
 * confirms" - and each suggestion shows its confidence so the user can
 * judge it.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import clsx from 'clsx';
import { Sparkles, Loader2 } from 'lucide-react';
import { Button, ConfidenceBadge } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { suggestCostCodes, type CostCodeSuggestion } from './api';

export interface CostCodeAssistProps {
  projectId: string;
  /** Seed text for the description box (usually the line note). */
  defaultText?: string;
  /** Called with the chosen cost code when the user clicks a suggestion. */
  onApply: (code: string) => void;
  disabled?: boolean;
}

export function CostCodeAssist({ projectId, defaultText, onApply, disabled }: CostCodeAssistProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(defaultText ?? '');
  const wrapRef = useRef<HTMLDivElement>(null);

  const suggestMut = useMutation({
    mutationFn: () => suggestCostCodes(projectId, text.trim(), 5),
  });

  // Close the popover on an outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const suggestions: CostCodeSuggestion[] = suggestMut.data?.suggestions ?? [];

  return (
    <div ref={wrapRef} className="relative">
      <Button
        type="button"
        variant="secondary"
        size="sm"
        icon={<Sparkles size={13} />}
        disabled={disabled}
        onClick={() => {
          setText(defaultText ?? '');
          setOpen((v) => !v);
        }}
        title={t('field_time.assist_hint', {
          defaultValue: 'Get AI cost-code suggestions - you confirm which to apply',
        })}
      >
        {t('field_time.assist', { defaultValue: 'Assist' })}
      </Button>

      {open && (
        <div
          className={clsx(
            'absolute right-0 z-30 mt-1 w-80 max-w-[80vw] rounded-lg border border-border-light',
            'bg-surface-elevated p-3 shadow-xl',
          )}
          role="dialog"
          aria-label={t('field_time.assist_title', { defaultValue: 'Cost-code assist' })}
        >
          <label className="mb-1.5 block text-xs font-medium text-content-primary">
            {t('field_time.assist_describe', { defaultValue: 'Describe the work' })}
          </label>
          <div className="flex gap-2">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t('field_time.assist_placeholder', {
                defaultValue: 'e.g. pour blinding to foundations',
              })}
              className="h-8 w-full rounded-lg border border-border-light bg-surface-primary px-2.5 text-sm text-content-primary"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && text.trim()) {
                  e.preventDefault();
                  suggestMut.mutate();
                }
              }}
            />
            <Button
              type="button"
              variant="primary"
              size="sm"
              disabled={!text.trim() || suggestMut.isPending}
              onClick={() => suggestMut.mutate()}
            >
              {suggestMut.isPending ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                t('field_time.assist_suggest', { defaultValue: 'Suggest' })
              )}
            </Button>
          </div>

          <p className="mt-2 text-2xs leading-relaxed text-content-tertiary">
            {t('field_time.assist_confirm_note', {
              defaultValue: 'Suggestions are ranked by confidence. Click one to apply it - nothing is applied automatically.',
            })}
          </p>

          {suggestMut.isError && (
            <p className="mt-2 text-xs text-semantic-error" role="alert">
              {getErrorMessage(suggestMut.error)}
            </p>
          )}

          {suggestMut.isSuccess && suggestions.length === 0 && (
            <p className="mt-2 text-xs text-content-tertiary">
              {t('field_time.assist_no_results', { defaultValue: 'No suggestions found.' })}
            </p>
          )}

          {suggestions.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1">
              {suggestions.map((s) => (
                <li key={s.code}>
                  <button
                    type="button"
                    onClick={() => {
                      onApply(s.code);
                      setOpen(false);
                    }}
                    className={clsx(
                      'flex w-full items-center gap-2 rounded-md border border-border-light',
                      'px-2.5 py-1.5 text-left transition-colors hover:bg-surface-secondary',
                    )}
                  >
                    <span className="font-mono text-xs font-semibold text-content-primary">
                      {s.code}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-xs text-content-secondary">
                      {s.label}
                    </span>
                    <ConfidenceBadge score={s.confidence} showScore className="shrink-0" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
