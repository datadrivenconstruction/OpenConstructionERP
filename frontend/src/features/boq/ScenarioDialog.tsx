// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ScenarioDialog — create a what-if scenario from the current BOQ.
 *
 * A scenario is a clone of the estimate linked back to its baseline via
 * `parent_estimate_id`. The optional rate adjustment multiplies every
 * position's unit_rate on the clone (the baseline is never touched), so the
 * user can model "what if every rate rises 5%" or "what if we win a 10%
 * discount" and then diff it against the baseline in the compare drawer.
 *
 * The server does the cloning and the decimal-safe rate maths; this dialog
 * only collects the name, the percentage delta, and an optional region/note
 * for provenance.
 */

import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { FlaskConical, X } from 'lucide-react';
import { boqApi } from './api';
import { useToastStore } from '@/stores/useToastStore';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { fmtFixed } from '@/shared/lib/formatters';
import { parseDecimalInput } from '@/shared/lib/parseDecimal';

export interface ScenarioDialogProps {
  boqId: string;
  /** Baseline estimate name, used to seed the scenario name. */
  baseName: string;
  isOpen: boolean;
  onClose: () => void;
  /** Called with the new scenario's BOQ id once it is created. */
  onCreated: (newBoqId: string) => void;
}

export function ScenarioDialog({ boqId, baseName, isOpen, onClose, onCreated }: ScenarioDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const panelRef = useRef<HTMLDivElement>(null);
  useFocusTrap(panelRef, isOpen);

  const [name, setName] = useState('');
  const [pct, setPct] = useState('0');
  const [region, setRegion] = useState('');
  const [note, setNote] = useState('');

  // Seed defaults each time the dialog opens (baseName may load after mount).
  useEffect(() => {
    if (isOpen) {
      setName(
        t('boq.scenario_default_name', {
          defaultValue: '{{name}} - scenario',
          name: baseName || t('boq.untitled_estimate', { defaultValue: 'Estimate' }),
        }),
      );
      setPct('0');
      setRegion('');
      setNote('');
    }
  }, [isOpen, baseName, t]);

  useEffect(() => {
    if (!isOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener('keydown', onKey, { capture: true });
    return () => document.removeEventListener('keydown', onKey, { capture: true });
  }, [isOpen, onClose]);

  const mutation = useMutation({
    mutationFn: () => {
      const parsed = parseDecimalInput(pct);
      const rate_factor = parsed !== null && parsed !== 0 ? 1 + parsed / 100 : undefined;
      return boqApi.createScenario(boqId, {
        name: name.trim() || baseName,
        rate_factor,
        region: region.trim() || undefined,
        note: note.trim() || undefined,
      });
    },
    onSuccess: (boq) => {
      queryClient.invalidateQueries({ queryKey: ['boqs'] });
      addToast({
        type: 'success',
        title: t('boq.scenario_created', { defaultValue: 'Scenario created' }),
      });
      onCreated(boq.id);
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('boq.scenario_failed', { defaultValue: 'Could not create scenario' }),
        message: err.message,
      });
    },
  });

  if (!isOpen) return null;

  const parsedPct = parseDecimalInput(pct);
  const factor = parsedPct === null ? 1 : 1 + parsedPct / 100;
  // Mirror the backend rule (rate_factor must be > 0): a percentage <= -100
  // would zero or negate every rate. Catch it client-side so the user sees why
  // instead of a backend 422, and never sees a "multiplied by 0.0000" preview.
  const pctInvalid = parsedPct !== null && factor <= 0;
  const showsPreview = parsedPct !== null && parsedPct !== 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-label={t('boq.scenario_title', { defaultValue: 'New what-if scenario' })}
        className="relative z-10 w-full max-w-md mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in focus:outline-none"
      >
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
              <FlaskConical size={16} />
            </span>
            <h2 className="text-base font-semibold text-content-primary">
              {t('boq.scenario_title', { defaultValue: 'New what-if scenario' })}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-6 pt-4 pb-2 space-y-4">
          <p className="text-xs text-content-secondary leading-relaxed">
            {t('boq.scenario_intro', {
              defaultValue:
                'Clones this estimate into a separate scenario you can adjust freely. The baseline stays untouched, and you can diff the two side by side at any time.',
            })}
          </p>

          <label className="block">
            <span className="text-xs font-medium text-content-secondary">
              {t('boq.scenario_name_label', { defaultValue: 'Scenario name' })}
            </span>
            <input
              autoFocus
              type="text"
              id="boq-scenario-name"
              name="boq-scenario-name"
              autoComplete="off"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              aria-label={t('boq.scenario_name_label', { defaultValue: 'Scenario name' })}
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-content-secondary">
              {t('boq.scenario_pct_label', { defaultValue: 'Adjust all unit rates by (%)' })}
            </span>
            <input
              type="text"
              inputMode="decimal"
              id="boq-scenario-pct"
              name="boq-scenario-pct"
              autoComplete="off"
              value={pct}
              onChange={(e) => setPct(e.target.value)}
              placeholder="0"
              className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm font-mono text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              aria-label={t('boq.scenario_pct_label', { defaultValue: 'Adjust all unit rates by (%)' })}
            />
            <span
              className={`mt-1 block text-2xs ${pctInvalid ? 'text-semantic-error' : 'text-content-tertiary'}`}
            >
              {pctInvalid
                ? t('boq.scenario_pct_invalid', {
                    defaultValue:
                      'Adjustment must be greater than -100% (rates cannot drop to zero or below).',
                  })
                : showsPreview
                  ? t('boq.scenario_pct_preview', {
                      defaultValue: 'Every unit rate is multiplied by {{factor}}.',
                      factor: fmtFixed(factor, 4),
                    })
                  : t('boq.scenario_pct_hint', {
                      defaultValue:
                        'Leave at 0 to copy rates as-is. Example: 5 = +5%, -10 = a 10% discount.',
                    })}
            </span>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs font-medium text-content-secondary">
                {t('boq.scenario_region_label', { defaultValue: 'Region (optional)' })}
              </span>
              <input
                type="text"
                id="boq-scenario-region"
                name="boq-scenario-region"
                autoComplete="off"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                placeholder={t('boq.scenario_region_ph', { defaultValue: 'e.g. Berlin' })}
                className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                aria-label={t('boq.scenario_region_label', { defaultValue: 'Region (optional)' })}
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-content-secondary">
                {t('boq.scenario_note_label', { defaultValue: 'Note (optional)' })}
              </span>
              <input
                type="text"
                id="boq-scenario-note"
                name="boq-scenario-note"
                autoComplete="off"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t('boq.scenario_note_ph', { defaultValue: 'What are you testing?' })}
                className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                aria-label={t('boq.scenario_note_label', { defaultValue: 'Note (optional)' })}
              />
            </label>
          </div>
        </div>

        <div className="flex gap-3 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium bg-surface-primary text-content-primary border border-border hover:bg-surface-secondary transition-all"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !name.trim() || pctInvalid}
            className="flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium text-white bg-oe-blue hover:bg-oe-blue-hover transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <FlaskConical size={15} />
            {mutation.isPending
              ? t('boq.scenario_creating', { defaultValue: 'Creating...' })
              : t('boq.scenario_create', { defaultValue: 'Create scenario' })}
          </button>
        </div>
      </div>
    </div>
  );
}
