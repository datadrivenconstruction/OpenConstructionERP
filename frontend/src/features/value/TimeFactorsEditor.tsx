// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Admin-only editor for the hours-saved minute factors. The "hours given back"
// headline on the value dashboard rests on a small lookup of "minutes one
// assisted action displaces". The seed defaults are deliberately conservative;
// an operator who has measured their own baseline tunes any factor here, per
// tenant. Values are minutes of saved effort, never money - they are typed as
// plain numbers and sent to the backend as strings (the lossless Decimal
// convention) where they are validated non-negative and capped. Setting a factor
// back to its seed default clears the override so the pair re-inherits the
// default. The editor is rendered only for admins by its parent.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RotateCcw } from 'lucide-react';

import { SideDrawer, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { getTimeFactors, putTimeFactors } from './api';
import type { TimeFactor } from './types';

interface TimeFactorsEditorProps {
  open: boolean;
  onClose: () => void;
}

// A human label for a (module, action) pair. The backend keeps the raw tokens
// (they match the activity-log columns); here we make them readable without
// inventing data - an unknown pair just shows its tokens.
const PAIR_LABELS: Record<string, string> = {
  'rfi/rfi_answered': 'RFI answered',
  'changeorders/change_order_logged': 'Change order logged',
  'changeorders/change_order_updated': 'Change order updated',
  'change_intelligence/comms_digest_generated': 'Correspondence digest generated',
  'change_intelligence/change_request_clarified': 'Change request clarified',
  'change_intelligence/delay_detected': 'Schedule delay detected',
  'claims_evidence/evidence_pack_assembled': 'Evidence pack assembled',
  'ai_estimator/ai_estimate_produced': 'AI estimate produced',
  'takeoff/takeoff_parsed': 'Takeoff parsed',
};

function pairKey(f: Pick<TimeFactor, 'module' | 'action'>): string {
  return `${f.module}/${f.action}`;
}

// A minute value is valid when it is a finite, non-negative number. We keep the
// raw text in state (so a half-typed value is not clobbered) and validate on the
// way out; the backend is the authority on the upper cap.
function isValidMinutes(raw: string): boolean {
  const trimmed = raw.trim();
  if (trimmed === '') return false;
  const n = Number(trimmed);
  return Number.isFinite(n) && n >= 0;
}

export function TimeFactorsEditor({ open, onClose }: TimeFactorsEditorProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Draft values keyed by pair, seeded from the server response. Editing never
  // mutates the query cache; Save sends the diff.
  const [draft, setDraft] = useState<Record<string, string>>({});

  const factorsQ = useQuery({
    queryKey: ['value', 'time-factors'],
    queryFn: getTimeFactors,
    enabled: open,
    retry: false,
    staleTime: 30_000,
  });

  // Reseed the draft whenever fresh data arrives (open, or after a save).
  useEffect(() => {
    if (factorsQ.data) {
      const next: Record<string, string> = {};
      for (const f of factorsQ.data.factors) next[pairKey(f)] = f.minutes;
      setDraft(next);
    }
  }, [factorsQ.data]);

  const rows = factorsQ.data?.factors ?? [];

  const saveMutation = useMutation({
    mutationFn: putTimeFactors,
    onSuccess: (data) => {
      queryClient.setQueryData(['value', 'time-factors'], data);
      // The headline hours figure depends on these factors; refresh every value
      // surface so the dashboard reflects the new numbers immediately.
      void queryClient.invalidateQueries({ queryKey: ['value', 'summary'] });
      void queryClient.invalidateQueries({ queryKey: ['value', 'hours'] });
      addToast({
        type: 'success',
        title: t('value.factors.saved', { defaultValue: 'Saved time factors' }),
      });
      onClose();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('value.factors.save_failed', { defaultValue: 'Could not save time factors' }),
        message: getErrorMessage(err),
      });
    },
  });

  // The set of pairs whose draft differs from the server value - the batch we
  // send. A pair reset to its default is included (the backend clears it).
  const changed = useMemo(() => {
    const out: { module: string; action: string; minutes: string }[] = [];
    for (const f of rows) {
      const key = pairKey(f);
      const value = (draft[key] ?? f.minutes).trim();
      if (value !== f.minutes && isValidMinutes(value)) {
        out.push({ module: f.module, action: f.action, minutes: value });
      }
    }
    return out;
  }, [rows, draft]);

  const anyInvalid = rows.some((f) => !isValidMinutes(draft[pairKey(f)] ?? f.minutes));
  const canSave = changed.length > 0 && !anyInvalid && !saveMutation.isPending;

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      busy={saveMutation.isPending}
      title={t('value.factors.title', { defaultValue: 'Hours-saved factors' })}
      subtitle={t('value.factors.subtitle', {
        defaultValue: 'Minutes of manual work each assisted action displaces',
      })}
    >
      <div className="space-y-4">
        <p className="text-sm text-content-tertiary">
          {t('value.factors.intro', {
            defaultValue:
              'These minute factors drive the "hours given back" headline. Defaults are deliberately conservative; tune them to your own measured baseline. Set a value back to its default to stop overriding it.',
          })}
        </p>

        {factorsQ.isLoading ? (
          <p className="text-sm text-content-tertiary">
            {t('common.loading', { defaultValue: 'Loading...' })}
          </p>
        ) : factorsQ.isError ? (
          <p className="text-sm text-semantic-error">{getErrorMessage(factorsQ.error)}</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('value.factors.empty', { defaultValue: 'No factors to edit.' })}
          </p>
        ) : (
          <ul className="space-y-2">
            {rows.map((f) => {
              const key = pairKey(f);
              const value = draft[key] ?? f.minutes;
              const invalid = !isValidMinutes(value);
              const isOverride = (value.trim() || f.minutes) !== (f.default_minutes ?? '');
              const canReset = f.default_minutes != null && value.trim() !== f.default_minutes;
              return (
                <li
                  key={key}
                  className="flex flex-wrap items-center gap-2 rounded-md border border-border-light p-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-content-primary">
                        {PAIR_LABELS[key] ?? key}
                      </span>
                      {isOverride ? (
                        <Badge variant="blue">
                          {t('value.factors.tuned', { defaultValue: 'Tuned' })}
                        </Badge>
                      ) : null}
                    </div>
                    <span className="text-xs text-content-tertiary">
                      {f.default_minutes != null
                        ? t('value.factors.default_hint', {
                            defaultValue: 'Default {{minutes}} min',
                            minutes: f.default_minutes,
                          })
                        : t('value.factors.custom_hint', { defaultValue: 'Custom action' })}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="number"
                      min={0}
                      step={1}
                      inputMode="decimal"
                      aria-label={t('value.factors.minutes_for', {
                        defaultValue: 'Minutes for {{label}}',
                        label: PAIR_LABELS[key] ?? key,
                      })}
                      aria-invalid={invalid}
                      value={value}
                      onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                      className={`w-20 rounded-md border bg-surface-primary px-2 py-1 text-right text-sm text-content-primary ${
                        invalid ? 'border-semantic-error' : 'border-border-light'
                      }`}
                    />
                    <span className="text-xs text-content-tertiary">
                      {t('value.factors.min_unit', { defaultValue: 'min' })}
                    </span>
                    <button
                      type="button"
                      disabled={!canReset}
                      onClick={() => {
                        if (f.default_minutes != null) {
                          setDraft((d) => ({ ...d, [key]: f.default_minutes as string }));
                        }
                      }}
                      title={t('value.factors.reset', { defaultValue: 'Reset to default' })}
                      aria-label={t('value.factors.reset', { defaultValue: 'Reset to default' })}
                      className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary disabled:opacity-30"
                    >
                      <RotateCcw className="h-4 w-4" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-border-light pt-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            disabled={!canSave}
            onClick={() => saveMutation.mutate(changed)}
            className="rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-oe-blue/90 disabled:opacity-40"
          >
            {saveMutation.isPending
              ? t('common.saving', { defaultValue: 'Saving...' })
              : t('value.factors.save', { defaultValue: 'Save factors' })}
          </button>
        </div>
      </div>
    </SideDrawer>
  );
}
