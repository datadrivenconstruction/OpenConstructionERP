// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Screen 2: "Here is what you will get".
 *
 * The register as a person would describe it to a colleague: its name, one
 * sentence, what each entry holds and what it checks. Below it, what the
 * platform proposes on top: records it could link to ("Connect to") and
 * functions it could carry ("Add functions"). Each proposal is a card with a
 * switch, a confidence band and one plain reason.
 *
 * Nothing is switched on for the person. A high-confidence proposal is still a
 * proposal (the platform's "AI proposes, human confirms"), so every switch
 * starts off and "Accept all" is one honest click away rather than a default.
 *
 * Everything else lives in "Fine-tune", closed unless the register was started
 * from scratch and so has nothing in it yet.
 */
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCheck, Link2, Plus, Puzzle, ShieldCheck, SlidersHorizontal, Sparkles } from 'lucide-react';
import clsx from 'clsx';

import { SuggestionCard } from '@/shared/ui';
import { Toggle } from '@/shared/ui/Toggle';

import type { ModuleSpec, Suggestion, Vocabulary } from '../api';
import { addRule, featuresOf, type SpecProblem } from '../draft';
import { BLOCK_REASONS, FEATURE_DESCRIPTIONS, TARGET_NAMES, say, suggestionReason, suggestionTitle } from '../copy';
import { applyAll, blockedBy, canApply, isApplied, toggleSuggestion } from '../suggestions';
import { isLockedFeature, isLockedField, type Baseline } from '../upgrade';
import { FineTune, LockedMark, autoRuleMessage } from './FineTune';
import { Disclosure, FieldTypeIcon, ModuleIcon, SectionHeading } from './shared';

interface ProposalScreenProps {
  spec: ModuleSpec;
  setSpec: (spec: ModuleSpec) => void;
  vocabulary: Vocabulary | undefined;
  problems: SpecProblem[];
  suggestions: Suggestion[];
  /** False against a server from before links and features; the proposals are then not shown. */
  featuresSupported: boolean;
  onNameChange: (name: string) => void;
  fineTuneOpen: boolean;
  setFineTuneOpen: (open: boolean) => void;
  advancedOpen: boolean;
  setAdvancedOpen: (open: boolean) => void;
  onKeyEdited: () => void;
  /** Adding to an installed module: its parts are locked and its name stays. */
  baseline?: Baseline | null;
}

/** True when this suggestion is already part of the installed module, and so stays on. */
function lockedOn(baseline: Baseline | null, spec: ModuleSpec, suggestion: Suggestion): boolean {
  if (!baseline) return false;
  if (suggestion.kind === 'feature') return isLockedFeature(baseline, suggestion.feature);
  const target = suggestion.target ?? suggestion.patch.field?.target;
  return spec.entity.fields.some((f) => f.type === 'link' && f.target === target && isLockedField(baseline, f));
}

export function ProposalScreen({
  spec,
  setSpec,
  vocabulary,
  problems,
  suggestions,
  featuresSupported,
  onNameChange,
  fineTuneOpen,
  setFineTuneOpen,
  advancedOpen,
  setAdvancedOpen,
  onKeyEdited,
  baseline = null,
}: ProposalScreenProps) {
  const { t } = useTranslation();
  const features = featuresOf(spec);

  // A deadline proposal about a field that has since been removed would apply
  // a reminder to nothing. Hidden until the field is back, unless it is on.
  const shown = featuresSupported
    ? suggestions.filter(
        (s) =>
          isApplied(spec, s) ||
          s.feature !== 'due' ||
          spec.entity.fields.some((f) => f.name === s.patch.due?.field),
      )
    : [];
  const links = shown.filter((s) => s.kind === 'link');
  const functions = shown.filter((s) => s.kind === 'feature');
  const pending = shown.filter((s) => !isApplied(spec, s) && canApply(spec, s, vocabulary));

  const firstField = spec.entity.fields.find((f) => f.label.trim() !== '' && f.name.trim() !== '');

  return (
    <div className="space-y-6" data-testid="module-builder-proposal">
      {/* The summary card: what a person would say about the register. */}
      <section className="rounded-2xl border border-border-light bg-gradient-to-b from-surface-secondary/50 to-surface-primary p-4 sm:p-5">
        <div className="flex items-start gap-3 sm:gap-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text sm:h-12 sm:w-12">
            <ModuleIcon name={spec.icon} />
          </span>
          <div className="min-w-0 flex-1">
            <label htmlFor="module-builder-name" className="sr-only">
              {t('module_builder.field_display_name', { defaultValue: 'Module name' })}
            </label>
            <input
              id="module-builder-name"
              value={spec.display_name}
              onChange={(e) => onNameChange(e.target.value)}
              placeholder={t('module_builder.name_placeholder', { defaultValue: 'Name your register' })}
              className="-mx-1.5 w-full rounded-lg border border-transparent bg-transparent px-1.5 py-0.5 text-lg font-semibold text-content-primary placeholder:text-content-quaternary hover:border-border-light focus:border-oe-blue/50 focus:outline-none focus:ring-2 focus:ring-oe-blue/20 sm:text-xl"
              data-testid="module-builder-name"
            />
            {spec.description.trim() && (
              <p className="mt-1 text-sm text-content-secondary">{spec.description}</p>
            )}
            {/* Marks the specification itself: a model wrote the first version,
                and editing it afterwards does not make that untrue. A spec
                built by hand shows nothing, the by-hand path being the
                unremarkable one. */}
            {spec.drafted_by === 'assistant' && (
              <p className="mt-2 flex flex-wrap items-center gap-1.5" data-testid="module-builder-ai-mark">
                <span className="inline-flex items-center gap-1 rounded-full bg-oe-blue/10 px-2 py-0.5 text-xs font-medium text-oe-blue-text">
                  <Sparkles className="h-3 w-3" />
                  {t('module_builder.spec_ai_drafted', { defaultValue: 'AI-drafted specification' })}
                </span>
                <span className="text-xs text-content-tertiary">
                  {t('module_builder.spec_ai_drafted_hint', {
                    defaultValue: 'A model wrote this from your sentence. Read every field before you install it.',
                  })}
                </span>
              </p>
            )}
          </div>
        </div>

        <div className="mt-5 space-y-4">
          <div>
            <SectionHeading>
              {t('module_builder.each_entry_holds', { defaultValue: 'Each entry holds' })}
            </SectionHeading>
            <ul className="flex flex-wrap gap-1.5" data-testid="module-builder-field-chips">
              {spec.entity.fields.map((field, i) => (
                <li
                  key={i}
                  className={clsx(
                    'inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
                    field.type === 'link'
                      ? 'border-oe-blue/30 bg-oe-blue/5 text-oe-blue-text'
                      : 'border-border-light bg-surface-primary text-content-secondary',
                  )}
                  title={vocabulary?.field_types.find((ft) => ft.type === field.type)?.label}
                >
                  <FieldTypeIcon type={field.type} size={12} className="shrink-0 opacity-70" />
                  <span className="truncate">
                    {field.label.trim() || t('module_builder.unnamed_field', { defaultValue: 'Unnamed field' })}
                  </span>
                  {field.unit.trim() && <span className="text-content-quaternary">{field.unit}</span>}
                  {field.type === 'link' && field.target && (
                    <span className="text-content-tertiary">→ {say(t, TARGET_NAMES[field.target])}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>

          <div>
            <SectionHeading icon={<ShieldCheck size={12} />}>
              {t('module_builder.checks_heading', { defaultValue: 'What it checks' })}
            </SectionHeading>
            {spec.rules.length > 0 ? (
              <ul className="space-y-1" data-testid="module-builder-check-list">
                {spec.rules.map((rule, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-content-secondary">
                    <span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-semantic-success" />
                    {/* The author's own words, as written. */}
                    <span className="min-w-0">{rule.message.trim() || rule.code}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="flex flex-wrap items-center gap-2 rounded-lg bg-semantic-warning-bg px-3 py-2 text-xs text-semantic-warning">
                <span>
                  {t('module_builder.no_checks', {
                    defaultValue: 'Every register checks at least one thing before an entry is saved.',
                  })}
                </span>
                {firstField && (
                  <button
                    type="button"
                    onClick={() =>
                      setSpec(addRule(spec, 'required', firstField.name, autoRuleMessage(t, 'required', firstField.label)))
                    }
                    className="inline-flex items-center gap-1 font-semibold underline-offset-2 hover:underline"
                    data-testid="module-builder-quick-rule"
                  >
                    <Plus size={12} />
                    {t('module_builder.quick_rule', {
                      field: firstField.label,
                      defaultValue: 'Check that {{field}} is filled in',
                    })}
                  </button>
                )}
              </div>
            )}
          </div>

          {features.status && (
            <div>
              <SectionHeading>{t('module_builder.stages_heading', { defaultValue: 'Stages' })}</SectionHeading>
              <ol className="flex flex-wrap items-center gap-1.5 text-xs">
                {features.status.states.map((state, i) => (
                  <li key={i} className="flex items-center gap-1.5">
                    {i > 0 && <span aria-hidden className="text-content-quaternary">→</span>}
                    <span
                      className={clsx(
                        'rounded-full px-2 py-0.5 font-medium',
                        state.done
                          ? 'bg-semantic-success-bg text-semantic-success'
                          : 'bg-surface-secondary text-content-secondary',
                      )}
                    >
                      {state.label}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      </section>

      {shown.length > 0 && (
        <section className="space-y-4" data-testid="module-builder-suggestions">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-content-primary">
                {t('module_builder.proposals_heading', { defaultValue: 'Make it more useful' })}
              </h3>
              <p className="text-xs text-content-tertiary">
                {t('module_builder.proposals_hint', {
                  defaultValue: 'Suggestions only. Switch on the ones you want; nothing is added until you do.',
                })}
              </p>
            </div>
            {pending.length > 1 && (
              <button
                type="button"
                onClick={() => setSpec(applyAll(spec, pending, vocabulary))}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-oe-blue/40 px-2.5 py-1.5 text-xs font-semibold text-oe-blue-text transition-colors hover:bg-oe-blue/10"
                data-testid="module-builder-accept-all"
              >
                <CheckCheck size={13} />
                {t('module_builder.accept_all', { defaultValue: 'Accept all suggested' })}
              </button>
            )}
          </div>

          {links.length > 0 && (
            <SuggestionGroup
              title={t('module_builder.connect_to', { defaultValue: 'Connect to' })}
              icon={<Link2 size={12} />}
              items={links}
              spec={spec}
              setSpec={setSpec}
              vocabulary={vocabulary}
              baseline={baseline}
            />
          )}
          {functions.length > 0 && (
            <SuggestionGroup
              title={t('module_builder.add_functions', { defaultValue: 'Add functions' })}
              icon={<Puzzle size={12} />}
              items={functions}
              spec={spec}
              setSpec={setSpec}
              vocabulary={vocabulary}
              baseline={baseline}
            />
          )}
        </section>
      )}

      {problems.length > 0 && !fineTuneOpen && (
        <div
          className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-semantic-warning-bg px-3 py-2 text-xs text-semantic-warning"
          data-testid="module-builder-problems"
        >
          <span>
            {t('module_builder.needs_attention', {
              count: problems.length,
              defaultValue_one: '{{count}} thing needs your attention before this can be created.',
              defaultValue_other: '{{count}} things need your attention before this can be created.',
            })}
          </span>
          <button
            type="button"
            onClick={() => {
              setFineTuneOpen(true);
              if (problems.some((p) => p.where === 'module' || p.where === 'entity:name')) setAdvancedOpen(true);
            }}
            className="font-semibold underline-offset-2 hover:underline"
            data-testid="module-builder-show-problems"
          >
            {t('module_builder.show_me', { defaultValue: 'Show me' })}
          </button>
        </div>
      )}

      <Disclosure
        open={fineTuneOpen}
        onToggle={() => setFineTuneOpen(!fineTuneOpen)}
        title={t('module_builder.fine_tune', { defaultValue: 'Fine-tune' })}
        hint={t('module_builder.fine_tune_hint', {
          defaultValue: 'Change the fields, the checks and the names. Optional.',
        })}
        icon={<SlidersHorizontal size={15} />}
        testId="module-builder-fine-tune"
      >
        <FineTune
          spec={spec}
          setSpec={setSpec}
          vocabulary={vocabulary}
          problems={problems}
          advancedOpen={advancedOpen}
          setAdvancedOpen={setAdvancedOpen}
          onKeyEdited={onKeyEdited}
          baseline={baseline}
        />
      </Disclosure>
    </div>
  );
}

function SuggestionGroup({
  title,
  icon,
  items,
  spec,
  setSpec,
  vocabulary,
  baseline,
}: {
  title: string;
  icon: ReactNode;
  items: Suggestion[];
  spec: ModuleSpec;
  setSpec: (spec: ModuleSpec) => void;
  vocabulary: Vocabulary | undefined;
  baseline: Baseline | null;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <SectionHeading icon={icon}>{title}</SectionHeading>
      <ul className="grid gap-2.5 sm:grid-cols-2">
        {items.map((suggestion) => {
          const on = isApplied(spec, suggestion);
          // A function the installed module already has stays on: switching it
          // off would take something away from entries already kept.
          const locked = on && lockedOn(baseline, spec, suggestion);
          const blocked = on ? null : blockedBy(spec, suggestion, vocabulary);
          const possible = blocked === null && !locked;
          const headline = suggestionTitle(t, suggestion);
          const reason = (
            <>
              {suggestionReason(t, suggestion)}
              {suggestion.kind === 'feature' && suggestion.feature && (
                <span className="mt-0.5 block text-content-tertiary">
                  {say(t, FEATURE_DESCRIPTIONS[suggestion.feature])}
                </span>
              )}
            </>
          );
          return (
            <li
              key={suggestion.id}
              className={clsx(
                'flex items-start gap-2 rounded-xl border transition-colors',
                on ? 'border-oe-blue/60 bg-oe-blue/5' : 'border-border-light bg-surface-primary',
                !possible && 'opacity-60',
              )}
              data-testid={`module-builder-suggestion-${suggestion.id}`}
              data-applied={on ? 'true' : 'false'}
              data-locked={locked ? 'true' : undefined}
            >
              <SuggestionCard
                title={headline}
                reason={
                  blocked === null ? reason : say(t, BLOCK_REASONS[blocked])
                }
                confidence={suggestion.confidence}
                className="min-w-0 flex-1 border-0 bg-transparent"
              />
              {locked && (
                <span className="shrink-0 pt-3">
                  <LockedMark />
                </span>
              )}
              <Toggle
                checked={on}
                disabled={!possible}
                // The card already shows the headline; the switch needs it as
                // its accessible name, not on screen a second time.
                label={<span className="sr-only">{headline}</span>}
                onChange={(next) => setSpec(toggleSuggestion(spec, suggestion, next, vocabulary))}
                className="shrink-0 pe-3 pt-3"
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}
