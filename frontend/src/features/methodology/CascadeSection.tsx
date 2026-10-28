// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The cascade editor - the centerpiece of the methodology editor.
//
// It edits, in one place:
//   * Base sets   - base_mapping: each leaf base token (labor, materials,
//                   machinery, equipment, ...) maps to the resource types that
//                   feed it. This is the "works (SMR) vs equipment" split.
//   * Composites  - named sums of leaf base tokens (e.g. SMR = labor +
//                   machinery + materials) that steps can apply to as one base.
//   * Markup steps- the ordered, sequential percentage / fixed steps, each
//                   applying to a chosen set of tokens (leaf bases, composites
//                   or EARLIER steps), ending in a VAT step.
//
// A live preview (CascadePreview.tsx) recomputes the cascade total from editable
// sample resource totals on every change using the faithful client mirror of
// the backend engine.

import { useTranslation } from 'react-i18next';
import {
  ArrowDown,
  ArrowUp,
  GripVertical,
  Plus,
  Receipt,
  Trash2,
} from 'lucide-react';
import { Badge, Button, Card } from '@/shared/ui';
import type { MarkupStep, StepKind } from './types';

const RESOURCE_TYPES = ['labor', 'material', 'machinery', 'equipment', 'subcontractor'];

const STEP_CATEGORIES = [
  'overhead',
  'profit',
  'temp_winter',
  'contractor_other',
  'insurance',
  'contingency',
  'tax',
  'other',
];

/** A unique-ish step key from a label, kept stable-ish for the cascade. */
function slugifyKey(label: string, existing: string[]): string {
  const base =
    label
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'step';
  if (!existing.includes(base)) return base;
  let n = 2;
  while (existing.includes(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}

interface CascadeSectionProps {
  readOnly: boolean;
  baseMapping: Record<string, string[]>;
  composites: Record<string, string[]>;
  steps: MarkupStep[];
  onChangeBaseMapping: (next: Record<string, string[]>) => void;
  onChangeComposites: (next: Record<string, string[]>) => void;
  onChangeSteps: (next: MarkupStep[]) => void;
}

export function CascadeSection({
  readOnly,
  baseMapping,
  composites,
  steps,
  onChangeBaseMapping,
  onChangeComposites,
  onChangeSteps,
}: CascadeSectionProps) {
  const { t } = useTranslation();

  const baseTokens = Object.keys(baseMapping);
  const compositeNames = Object.keys(composites);

  // ── Base sets ──────────────────────────────────────────────────────
  const toggleResourceType = (token: string, type: string) => {
    const current = baseMapping[token] ?? [];
    const next = current.includes(type)
      ? current.filter((x) => x !== type)
      : [...current, type];
    onChangeBaseMapping({ ...baseMapping, [token]: next });
  };

  const addBaseToken = () => {
    let name = 'base';
    let n = 1;
    while (baseTokens.includes(name)) {
      n += 1;
      name = `base_${n}`;
    }
    onChangeBaseMapping({ ...baseMapping, [name]: [] });
  };

  const renameBaseToken = (oldName: string, newNameRaw: string) => {
    const newName = newNameRaw.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_');
    if (!newName || newName === oldName || baseTokens.includes(newName)) return;
    const next: Record<string, string[]> = {};
    for (const [k, v] of Object.entries(baseMapping)) {
      next[k === oldName ? newName : k] = v;
    }
    onChangeBaseMapping(next);
    // Rewire composites + step bases that referenced the old token.
    const nextComposites: Record<string, string[]> = {};
    for (const [k, members] of Object.entries(composites)) {
      nextComposites[k] = members.map((m) => (m === oldName ? newName : m));
    }
    onChangeComposites(nextComposites);
    onChangeSteps(
      steps.map((s) => ({ ...s, base: s.base.map((b) => (b === oldName ? newName : b)) })),
    );
  };

  const removeBaseToken = (name: string) => {
    const next = { ...baseMapping };
    delete next[name];
    onChangeBaseMapping(next);
    // Drop references from composites + steps.
    const nextComposites: Record<string, string[]> = {};
    for (const [k, members] of Object.entries(composites)) {
      nextComposites[k] = members.filter((m) => m !== name);
    }
    onChangeComposites(nextComposites);
    onChangeSteps(steps.map((s) => ({ ...s, base: s.base.filter((b) => b !== name) })));
  };

  // ── Composites ─────────────────────────────────────────────────────
  const addComposite = () => {
    let name = 'SMR';
    if (compositeNames.includes(name)) {
      let n = 2;
      while (compositeNames.includes(`group_${n}`)) n += 1;
      name = `group_${n}`;
    }
    onChangeComposites({ ...composites, [name]: [] });
  };

  const renameComposite = (oldName: string, newNameRaw: string) => {
    const newName = newNameRaw.trim().replace(/\s+/g, '_');
    if (!newName || newName === oldName || compositeNames.includes(newName)) return;
    if (baseTokens.includes(newName)) return; // would collide with a leaf base
    const next: Record<string, string[]> = {};
    for (const [k, v] of Object.entries(composites)) next[k === oldName ? newName : k] = v;
    onChangeComposites(next);
    onChangeSteps(
      steps.map((s) => ({ ...s, base: s.base.map((b) => (b === oldName ? newName : b)) })),
    );
  };

  const toggleCompositeMember = (name: string, token: string) => {
    const current = composites[name] ?? [];
    const next = current.includes(token)
      ? current.filter((x) => x !== token)
      : [...current, token];
    onChangeComposites({ ...composites, [name]: next });
  };

  const removeComposite = (name: string) => {
    const next = { ...composites };
    delete next[name];
    onChangeComposites(next);
    onChangeSteps(steps.map((s) => ({ ...s, base: s.base.filter((b) => b !== name) })));
  };

  // ── Steps ──────────────────────────────────────────────────────────
  const addStep = () => {
    const key = slugifyKey('step', steps.map((s) => s.key));
    const next: MarkupStep = {
      key,
      label: '',
      category: 'other',
      kind: 'percentage',
      rate: '0',
      amount: '0',
      // Default a new step to apply on top of everything computed so far: all
      // leaf bases plus all prior step keys. The user trims this down.
      base: [...baseTokens, ...steps.map((s) => s.key)],
    };
    onChangeSteps([...steps, next]);
  };

  const addVatStep = () => {
    const key = slugifyKey('vat', steps.map((s) => s.key));
    const next: MarkupStep = {
      key,
      label: 'VAT',
      category: 'tax',
      kind: 'percentage',
      rate: '0',
      amount: '0',
      base: [...baseTokens, ...steps.map((s) => s.key)],
    };
    onChangeSteps([...steps, next]);
  };

  const updateStep = (index: number, patch: Partial<MarkupStep>) => {
    onChangeSteps(steps.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const removeStep = (index: number) => {
    const removed = steps[index];
    if (!removed) return;
    const removedKey = removed.key;
    const next = steps
      .filter((_, i) => i !== index)
      .map((s) => ({ ...s, base: s.base.filter((b) => b !== removedKey) }));
    onChangeSteps(next);
  };

  const moveStep = (index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= steps.length) return;
    const a = steps[index];
    const b = steps[target];
    if (!a || !b) return;
    const next = [...steps];
    next[index] = b;
    next[target] = a;
    // Moving a step earlier can turn a now-later step's reference into a
    // forward reference; the preview surfaces that as an error so the user
    // sees it immediately. We do not silently rewrite their intent.
    onChangeSteps(next);
  };

  const toggleStepBase = (index: number, token: string) => {
    const step = steps[index];
    if (!step) return;
    const next = step.base.includes(token)
      ? step.base.filter((x) => x !== token)
      : [...step.base, token];
    updateStep(index, { base: next });
  };

  return (
    <div className="space-y-5">
      {/* ── Base sets ─────────────────────────────────────────────────── */}
      <Card padding="lg">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('methodology.cascade.base_sets.title', { defaultValue: 'Base sets' })}
            </h3>
            <p className="mt-0.5 text-xs text-content-secondary">
              {t('methodology.cascade.base_sets.subtitle', {
                defaultValue:
                  'Each base set groups the resource types that feed it. This is the works vs equipment split: e.g. machinery feeds works (SMR), installed equipment stays separate.',
              })}
            </p>
          </div>
          {!readOnly && (
            <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={addBaseToken}>
              {t('methodology.cascade.base_sets.add', { defaultValue: 'Add base' })}
            </Button>
          )}
        </div>

        <div className="mt-4 space-y-3">
          {baseTokens.length === 0 ? (
            <p className="text-sm italic text-content-tertiary">
              {t('methodology.cascade.base_sets.empty', {
                defaultValue: 'No base sets. Add one to map resource types into the cascade.',
              })}
            </p>
          ) : (
            baseTokens.map((token) => (
              <div
                key={token}
                className="rounded-lg border border-border-light bg-surface-secondary/20 px-3 py-2.5"
              >
                <div className="flex items-center gap-2">
                  <input
                    value={token}
                    disabled={readOnly}
                    onChange={(e) => renameBaseToken(token, e.target.value)}
                    className="h-8 w-44 rounded-md border border-border bg-surface-primary px-2 font-mono text-xs text-content-primary disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                    aria-label={t('methodology.cascade.base_sets.name_label', {
                      defaultValue: 'Base set name',
                    })}
                  />
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() => removeBaseToken(token)}
                      className="ml-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error"
                      aria-label={t('common.delete', { defaultValue: 'Delete' })}
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {RESOURCE_TYPES.map((type) => {
                    const on = (baseMapping[token] ?? []).includes(type);
                    return (
                      <button
                        key={type}
                        type="button"
                        disabled={readOnly}
                        aria-pressed={on}
                        onClick={() => toggleResourceType(token, type)}
                        className={
                          'rounded-full border px-2.5 py-1 text-2xs font-medium transition-colors disabled:opacity-60 ' +
                          (on
                            ? 'border-oe-blue bg-oe-blue/10 text-oe-blue-text'
                            : 'border-border-light text-content-tertiary hover:bg-surface-secondary')
                        }
                      >
                        {type}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>
      </Card>

      {/* ── Composites ────────────────────────────────────────────────── */}
      <Card padding="lg">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('methodology.cascade.composites.title', { defaultValue: 'Composite base sets' })}
            </h3>
            <p className="mt-0.5 text-xs text-content-secondary">
              {t('methodology.cascade.composites.subtitle', {
                defaultValue:
                  'A named sum of base sets a step can apply to as one base. For example SMR (СМР) = labor + machinery + materials.',
              })}
            </p>
          </div>
          {!readOnly && (
            <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={addComposite}>
              {t('methodology.cascade.composites.add', { defaultValue: 'Add composite' })}
            </Button>
          )}
        </div>

        <div className="mt-4 space-y-3">
          {compositeNames.length === 0 ? (
            <p className="text-sm italic text-content-tertiary">
              {t('methodology.cascade.composites.empty', {
                defaultValue: 'No composites. Steps can still apply to individual base sets.',
              })}
            </p>
          ) : (
            compositeNames.map((name) => (
              <div
                key={name}
                className="rounded-lg border border-border-light bg-surface-secondary/20 px-3 py-2.5"
              >
                <div className="flex items-center gap-2">
                  <input
                    value={name}
                    disabled={readOnly}
                    onChange={(e) => renameComposite(name, e.target.value)}
                    className="h-8 w-44 rounded-md border border-border bg-surface-primary px-2 font-mono text-xs text-content-primary disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                    aria-label={t('methodology.cascade.composites.name_label', {
                      defaultValue: 'Composite name',
                    })}
                  />
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() => removeComposite(name)}
                      className="ml-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error"
                      aria-label={t('common.delete', { defaultValue: 'Delete' })}
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {baseTokens.length === 0 ? (
                    <span className="text-2xs italic text-content-tertiary">
                      {t('methodology.cascade.composites.no_bases', {
                        defaultValue: 'Add base sets first.',
                      })}
                    </span>
                  ) : (
                    baseTokens.map((token) => {
                      const on = (composites[name] ?? []).includes(token);
                      return (
                        <button
                          key={token}
                          type="button"
                          disabled={readOnly}
                          aria-pressed={on}
                          onClick={() => toggleCompositeMember(name, token)}
                          className={
                            'rounded-full border px-2.5 py-1 font-mono text-2xs transition-colors disabled:opacity-60 ' +
                            (on
                              ? 'border-oe-blue bg-oe-blue/10 text-oe-blue-text'
                              : 'border-border-light text-content-tertiary hover:bg-surface-secondary')
                          }
                        >
                          {token}
                        </button>
                      );
                    })
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </Card>

      {/* ── Markup steps ──────────────────────────────────────────────── */}
      <Card padding="lg">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('methodology.cascade.steps.title', { defaultValue: 'Markup steps' })}
            </h3>
            <p className="mt-0.5 text-xs text-content-secondary">
              {t('methodology.cascade.steps.subtitle', {
                defaultValue:
                  'Sequential markups. Each step applies its percentage (or fixed amount) to the base sets, composites and EARLIER steps you select. Order matters - a step can only build on steps above it.',
              })}
            </p>
          </div>
          {!readOnly && (
            <div className="flex shrink-0 gap-2">
              <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={addStep}>
                {t('methodology.cascade.steps.add', { defaultValue: 'Add step' })}
              </Button>
              <Button variant="secondary" size="sm" icon={<Receipt size={14} />} onClick={addVatStep}>
                {t('methodology.cascade.steps.add_vat', { defaultValue: 'Add VAT' })}
              </Button>
            </div>
          )}
        </div>

        <div className="mt-4 space-y-3">
          {steps.length === 0 ? (
            <p className="text-sm italic text-content-tertiary">
              {t('methodology.cascade.steps.empty', {
                defaultValue: 'No markup steps yet. The direct cost would be the final total.',
              })}
            </p>
          ) : (
            steps.map((step, index) => {
              // The tokens this step is allowed to reference: leaf bases,
              // composites, and the keys of EARLIER steps only.
              const earlierStepKeys = steps.slice(0, index).map((s) => s.key);
              const selectableTokens = [...baseTokens, ...compositeNames, ...earlierStepKeys];
              return (
                <div
                  key={`${step.key}-${index}`}
                  className="rounded-lg border border-border-light bg-surface-primary px-3 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-content-tertiary" aria-hidden>
                      <GripVertical size={15} />
                    </span>
                    <span className="inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-surface-secondary px-1.5 text-2xs font-semibold tabular-nums text-content-secondary">
                      {index + 1}
                    </span>
                    <input
                      value={step.label}
                      disabled={readOnly}
                      placeholder={t('methodology.cascade.steps.label_placeholder', {
                        defaultValue: 'Step name (e.g. Overhead)',
                      })}
                      onChange={(e) => {
                        const label = e.target.value;
                        // Keep the key in sync only while it is still auto-derived
                        // and the step is new-ish (blank or default). Once a step
                        // is referenced by a later step, renaming the key would
                        // break that reference, so we keep the existing key.
                        updateStep(index, { label });
                      }}
                      className="h-8 min-w-[10rem] flex-1 rounded-md border border-border bg-surface-primary px-2 text-sm text-content-primary disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                    />
                    {step.category === 'tax' && (
                      <Badge variant="blue" size="sm">
                        {t('methodology.cascade.steps.vat_badge', { defaultValue: 'VAT' })}
                      </Badge>
                    )}
                    {!readOnly && (
                      <div className="flex items-center gap-0.5">
                        <button
                          type="button"
                          onClick={() => moveStep(index, -1)}
                          disabled={index === 0}
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary disabled:opacity-30"
                          aria-label={t('methodology.cascade.steps.move_up', { defaultValue: 'Move up' })}
                        >
                          <ArrowUp size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => moveStep(index, 1)}
                          disabled={index === steps.length - 1}
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary disabled:opacity-30"
                          aria-label={t('methodology.cascade.steps.move_down', { defaultValue: 'Move down' })}
                        >
                          <ArrowDown size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => removeStep(index)}
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error"
                          aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    )}
                  </div>

                  <div className="mt-2.5 flex flex-wrap items-end gap-3">
                    <label className="flex flex-col gap-1">
                      <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                        {t('methodology.cascade.steps.kind', { defaultValue: 'Type' })}
                      </span>
                      <select
                        value={step.kind}
                        disabled={readOnly}
                        onChange={(e) => updateStep(index, { kind: e.target.value as StepKind })}
                        className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary disabled:opacity-60"
                      >
                        <option value="percentage">
                          {t('methodology.cascade.steps.kind_pct', { defaultValue: 'Percentage' })}
                        </option>
                        <option value="fixed">
                          {t('methodology.cascade.steps.kind_fixed', { defaultValue: 'Fixed amount' })}
                        </option>
                      </select>
                    </label>

                    {step.kind === 'percentage' ? (
                      <label className="flex flex-col gap-1">
                        <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                          {t('methodology.cascade.steps.rate', { defaultValue: 'Rate %' })}
                        </span>
                        <input
                          type="text"
                          inputMode="decimal"
                          value={step.rate}
                          disabled={readOnly}
                          onChange={(e) => updateStep(index, { rate: e.target.value })}
                          className="h-8 w-24 rounded-md border border-border bg-surface-primary px-2 text-xs tabular-nums text-content-primary disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                        />
                      </label>
                    ) : (
                      <label className="flex flex-col gap-1">
                        <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                          {t('methodology.cascade.steps.amount', { defaultValue: 'Amount' })}
                        </span>
                        <input
                          type="text"
                          inputMode="decimal"
                          value={step.amount}
                          disabled={readOnly}
                          onChange={(e) => updateStep(index, { amount: e.target.value })}
                          className="h-8 w-28 rounded-md border border-border bg-surface-primary px-2 text-xs tabular-nums text-content-primary disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                        />
                      </label>
                    )}

                    <label className="flex flex-col gap-1">
                      <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                        {t('methodology.cascade.steps.category', { defaultValue: 'Category' })}
                      </span>
                      <select
                        value={step.category}
                        disabled={readOnly}
                        onChange={(e) => updateStep(index, { category: e.target.value })}
                        className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary disabled:opacity-60"
                      >
                        {STEP_CATEGORIES.map((cat) => (
                          <option key={cat} value={cat}>
                            {cat}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>

                  <div className="mt-2.5">
                    <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                      {t('methodology.cascade.steps.applies_to', { defaultValue: 'Applies to' })}
                    </span>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {selectableTokens.length === 0 ? (
                        <span className="text-2xs italic text-content-tertiary">
                          {t('methodology.cascade.steps.no_tokens', {
                            defaultValue: 'Add base sets or earlier steps to apply this to.',
                          })}
                        </span>
                      ) : (
                        selectableTokens.map((token) => {
                          const on = step.base.includes(token);
                          const isStepRef = earlierStepKeys.includes(token);
                          return (
                            <button
                              key={token}
                              type="button"
                              disabled={readOnly}
                              aria-pressed={on}
                              onClick={() => toggleStepBase(index, token)}
                              className={
                                'rounded-full border px-2.5 py-1 font-mono text-2xs transition-colors disabled:opacity-60 ' +
                                (on
                                  ? isStepRef
                                    ? 'border-violet-400 bg-violet-500/10 text-violet-700 dark:text-violet-300'
                                    : 'border-oe-blue bg-oe-blue/10 text-oe-blue-text'
                                  : 'border-border-light text-content-tertiary hover:bg-surface-secondary')
                              }
                              title={
                                isStepRef
                                  ? t('methodology.cascade.steps.token_step', {
                                      defaultValue: 'Earlier step',
                                    })
                                  : undefined
                              }
                            >
                              {token}
                            </button>
                          );
                        })
                      )}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </Card>
    </div>
  );
}
