// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Create / edit a user-authored AI agent — a simple, guided builder.
//
// The whole point is that a non-technical estimator never writes a raw system
// prompt. They answer a few plain questions (who the agent acts as, what it
// helps with, who the answer is for, how to shape it) plus pick a name, icon
// and category. The backend compiles those guided fields into a well-formed
// system prompt. An optional "advanced" disclosure lets a power user paste a
// raw prompt instead, but it is never the default path.
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Loader2, Sparkles, ChevronDown, Wand2, Clock, Wrench, Zap } from 'lucide-react';
import clsx from 'clsx';

import { resolveAgentIcon } from './agentMeta';
import { SchedulePanel } from './SchedulePanel';
import { ToolPanel } from './ToolPanel';
import { TriggerPanel } from './TriggerPanel';
import type {
  CustomAgent,
  CustomAgentInput,
  EventTriggerDescriptor,
  GuidedAgentSpec,
  ToolWithPermission,
} from '../api';

/** Schedule state collected by the builder and persisted by the parent. */
export interface BuilderSchedule {
  cron: string | null;
  enabled: boolean;
  scheduleInput: string;
}

/** Everything the builder emits on save: the agent + its automation. */
export interface BuilderSubmit {
  agent: CustomAgentInput;
  schedule: BuilderSchedule;
  allowedTools: string[];
  triggers: string[];
}

// ── Pickable icons + categories ─────────────────────────────────────────────
// A curated subset of the icons the gallery already knows how to render
// (agentMeta.ICON_BY_KEY), so a custom agent's glyph always resolves.
const ICON_CHOICES = [
  'sparkles',
  'calculator',
  'ruler',
  'layers',
  'tags',
  'filetext',
  'filesearch',
  'clipboardcheck',
  'shieldcheck',
  'scale',
  'barchart',
  'trendingup',
  'gauge',
  'receipt',
  'package',
  'lightbulb',
  'search',
  'brain',
  'wrench',
  'bot',
] as const;

interface CategoryChoice {
  key: string;
  labelKey: string;
  defaultLabel: string;
}

const CATEGORY_CHOICES: CategoryChoice[] = [
  { key: 'estimating', labelKey: 'agents.category.estimating', defaultLabel: 'Estimating' },
  { key: 'quality', labelKey: 'agents.category.quality', defaultLabel: 'Quality & compliance' },
  { key: 'documents', labelKey: 'agents.category.documents', defaultLabel: 'Documents' },
  { key: 'analytics', labelKey: 'agents.category.analytics', defaultLabel: 'Analytics' },
  { key: 'planning', labelKey: 'agents.category.planning', defaultLabel: 'Planning' },
  { key: 'general', labelKey: 'agents.category.general', defaultLabel: 'General' },
];

interface CustomAgentBuilderProps {
  open: boolean;
  /** When set, the form opens in edit mode pre-filled from this agent. */
  editing?: CustomAgent | null;
  saving: boolean;
  error?: string | null;
  /** The full tool catalogue (with required permissions) for the Tools panel. */
  tools?: ToolWithPermission[];
  /** The event-trigger catalogue (with availability) for the Triggers panel. */
  triggerCatalogue?: EventTriggerDescriptor[];
  /** Initial schedule, pre-loaded by the parent when editing. */
  initialSchedule?: BuilderSchedule | null;
  /** Next scheduled run (ISO UTC) loaded by the parent when editing. */
  initialNextRunAt?: string | null;
  /** Initially-granted tool slugs, pre-loaded by the parent when editing. */
  initialTools?: string[];
  /** Initially-subscribed event triggers, pre-loaded by the parent when editing. */
  initialTriggers?: string[];
  /** True while the parent loads the agent's automation envelope. */
  loadingAutomation?: boolean;
  onClose: () => void;
  onSubmit: (submit: BuilderSubmit) => void;
}

const EMPTY_GUIDED: GuidedAgentSpec = {
  role: '',
  goal: '',
  audience: '',
  output_format: '',
  extra_guidance: '',
};

/**
 * The guided custom-agent builder modal. Beautiful, minimal, and forgiving:
 * only the name and the "what it helps with" goal are required.
 */
const EMPTY_SCHEDULE: BuilderSchedule = { cron: null, enabled: false, scheduleInput: '' };

export function CustomAgentBuilder({
  open,
  editing,
  saving,
  error,
  tools = [],
  triggerCatalogue = [],
  initialSchedule = null,
  initialNextRunAt = null,
  initialTools = [],
  initialTriggers = [],
  loadingAutomation = false,
  onClose,
  onSubmit,
}: CustomAgentBuilderProps): JSX.Element | null {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);

  const [displayName, setDisplayName] = useState('');
  const [tagline, setTagline] = useState('');
  const [icon, setIcon] = useState<string>('sparkles');
  const [category, setCategory] = useState('general');
  const [guided, setGuided] = useState<GuidedAgentSpec>(EMPTY_GUIDED);
  const [examplesText, setExamplesText] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [rawPrompt, setRawPrompt] = useState('');
  // Automation state (Item 29) — persisted by the parent after the agent saves.
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [triggersOpen, setTriggersOpen] = useState(false);
  const [schedule, setSchedule] = useState<BuilderSchedule>(EMPTY_SCHEDULE);
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [selectedTriggers, setSelectedTriggers] = useState<string[]>([]);

  // (Re)seed the form whenever the modal opens or the target changes.
  useEffect(() => {
    if (!open) return;
    if (editing) {
      setDisplayName(editing.display_name ?? '');
      setTagline(editing.tagline ?? '');
      setIcon(editing.icon || 'sparkles');
      setCategory(editing.category || 'general');
      setGuided({ ...EMPTY_GUIDED, ...(editing.guided ?? { goal: '' }) });
      setExamplesText((editing.example_prompts ?? []).join('\n'));
      // Only expose the raw prompt in advanced mode when there was no guided
      // spec to re-hydrate (i.e. the agent was authored with a raw prompt).
      const hadGuided = !!editing.guided;
      setAdvancedOpen(!hadGuided);
      setRawPrompt(hadGuided ? '' : editing.system_prompt ?? '');
    } else {
      setDisplayName('');
      setTagline('');
      setIcon('sparkles');
      setCategory('general');
      setGuided(EMPTY_GUIDED);
      setExamplesText('');
      setAdvancedOpen(false);
      setRawPrompt('');
    }
    // Reset the automation sections on (re)open; the parent pushes the editing
    // agent's saved schedule/tools/triggers via the initial* props once loaded.
    setScheduleOpen(false);
    setToolsOpen(false);
    setTriggersOpen(false);
  }, [open, editing]);

  // Seed automation state from the parent-loaded envelope (edit mode).
  useEffect(() => {
    if (!open) return;
    setSchedule(initialSchedule ?? EMPTY_SCHEDULE);
    setSelectedTools(initialTools ?? []);
    setSelectedTriggers(initialTriggers ?? []);
    if (initialSchedule?.cron) setScheduleOpen(true);
    if ((initialTools ?? []).length > 0) setToolsOpen(true);
    if ((initialTriggers ?? []).length > 0) setTriggersOpen(true);
  }, [open, initialSchedule, initialTools, initialTriggers]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, onClose]);

  if (!open) return null;

  const useRaw = advancedOpen && rawPrompt.trim().length > 0;
  const nameOk = displayName.trim().length >= 2;
  const promptOk = useRaw || guided.goal.trim().length >= 3;
  const canSubmit = nameOk && promptOk && !saving;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    const examples = examplesText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(0, 6);
    const input: CustomAgentInput = {
      display_name: displayName.trim(),
      tagline: tagline.trim(),
      description: tagline.trim(),
      category,
      icon,
      example_prompts: examples,
      // Guided wins unless the user deliberately pasted a raw prompt.
      guided: useRaw
        ? null
        : {
            role: guided.role?.trim() || '',
            goal: guided.goal.trim(),
            audience: guided.audience?.trim() || '',
            output_format: guided.output_format?.trim() || '',
            extra_guidance: guided.extra_guidance?.trim() || '',
          },
      system_prompt: useRaw ? rawPrompt.trim() : '',
    };
    onSubmit({ agent: input, schedule, allowedTools: selectedTools, triggers: selectedTriggers });
  };

  const PreviewIcon = resolveAgentIcon(icon);
  const inputClass = clsx(
    'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2',
    'text-sm text-content-primary placeholder:text-content-quaternary',
    'focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/20',
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in" onClick={onClose} />

      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={
          editing
            ? t('agents.builder.edit_title', { defaultValue: 'Edit your agent' })
            : t('agents.builder.create_title', { defaultValue: 'Create your own agent' })
        }
        className={clsx(
          'relative z-10 mx-4 flex max-h-[90vh] w-full max-w-lg flex-col',
          'rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in',
        )}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-6 pb-3 pt-5">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
              <PreviewIcon className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-base font-semibold text-content-primary">
                {editing
                  ? t('agents.builder.edit_title', { defaultValue: 'Edit your agent' })
                  : t('agents.builder.create_title', { defaultValue: 'Create your own agent' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('agents.builder.subtitle', {
                  defaultValue: 'Answer a few questions - we turn them into a ready-to-run agent.',
                })}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-secondary"
            aria-label={t('common.cancel', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-2">
            {/* Name */}
            <div>
              <label htmlFor="ca-name" className="mb-1 block text-xs font-medium text-content-secondary">
                {t('agents.builder.name_label', { defaultValue: 'Agent name' })}
                <span className="ml-0.5 text-semantic-error">*</span>
              </label>
              <input
                id="ca-name"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                maxLength={120}
                required
                aria-required="true"
                placeholder={t('agents.builder.name_placeholder', {
                  defaultValue: 'e.g. Variation Letter Helper',
                })}
                className={inputClass}
              />
            </div>

            {/* Tagline */}
            <div>
              <label htmlFor="ca-tagline" className="mb-1 block text-xs font-medium text-content-secondary">
                {t('agents.builder.tagline_label', { defaultValue: 'Short description' })}
              </label>
              <input
                id="ca-tagline"
                type="text"
                value={tagline}
                onChange={(e) => setTagline(e.target.value)}
                maxLength={280}
                placeholder={t('agents.builder.tagline_placeholder', {
                  defaultValue: 'One line shown on the agent card',
                })}
                className={inputClass}
              />
            </div>

            {/* Icon picker */}
            <div>
              <span className="mb-1.5 block text-xs font-medium text-content-secondary">
                {t('agents.builder.icon_label', { defaultValue: 'Icon' })}
              </span>
              <div className="flex flex-wrap gap-1.5">
                {ICON_CHOICES.map((key) => {
                  const Glyph = resolveAgentIcon(key);
                  const active = icon === key;
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setIcon(key)}
                      aria-pressed={active}
                      aria-label={key}
                      className={clsx(
                        'flex h-9 w-9 items-center justify-center rounded-lg border transition-all',
                        active
                          ? 'border-oe-blue/60 bg-oe-blue text-content-inverse ring-2 ring-oe-blue/20'
                          : 'border-border-light bg-surface-secondary/60 text-content-secondary hover:border-oe-blue/40 hover:bg-oe-blue-subtle hover:text-oe-blue-text',
                      )}
                    >
                      <Glyph className="h-4 w-4" aria-hidden="true" />
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Category pills */}
            <div>
              <span className="mb-1.5 block text-xs font-medium text-content-secondary">
                {t('agents.builder.category_label', { defaultValue: 'Category' })}
              </span>
              <div className="flex flex-wrap gap-1.5">
                {CATEGORY_CHOICES.map((cat) => {
                  const active = category === cat.key;
                  return (
                    <button
                      key={cat.key}
                      type="button"
                      onClick={() => setCategory(cat.key)}
                      aria-pressed={active}
                      className={clsx(
                        'rounded-full border px-3 py-1.5 text-xs font-medium transition-all',
                        active
                          ? 'border-oe-blue/20 bg-oe-blue/10 text-oe-blue'
                          : 'border-transparent bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
                      )}
                    >
                      {t(cat.labelKey, { defaultValue: cat.defaultLabel })}
                    </button>
                  );
                })}
              </div>
            </div>

            {!advancedOpen && (
              <>
                {/* Guided builder */}
                <div className="rounded-xl border border-border-light bg-surface-secondary/40 p-3">
                  <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-content-secondary">
                    <Wand2 className="h-3.5 w-3.5 text-oe-blue" aria-hidden="true" />
                    {t('agents.builder.guided_heading', { defaultValue: 'Tell us what it should do' })}
                  </div>

                  <div className="space-y-3">
                    <div>
                      <label htmlFor="ca-role" className="mb-1 block text-xs text-content-tertiary">
                        {t('agents.builder.role_label', { defaultValue: 'It should act as…' })}
                      </label>
                      <input
                        id="ca-role"
                        type="text"
                        value={guided.role}
                        onChange={(e) => setGuided((g) => ({ ...g, role: e.target.value }))}
                        maxLength={200}
                        placeholder={t('agents.builder.role_placeholder', {
                          defaultValue: 'a senior quantity surveyor',
                        })}
                        className={inputClass}
                      />
                    </div>

                    <div>
                      <label htmlFor="ca-goal" className="mb-1 block text-xs text-content-tertiary">
                        {t('agents.builder.goal_label', { defaultValue: 'What should it help with?' })}
                        <span className="ml-0.5 text-semantic-error">*</span>
                      </label>
                      <textarea
                        id="ca-goal"
                        value={guided.goal}
                        onChange={(e) => setGuided((g) => ({ ...g, goal: e.target.value }))}
                        rows={3}
                        maxLength={2000}
                        required
                        aria-required="true"
                        placeholder={t('agents.builder.goal_placeholder', {
                          defaultValue:
                            'Draft clear variation cover letters from a short note about the change and its cost impact.',
                        })}
                        className={inputClass}
                      />
                    </div>

                    <div>
                      <label htmlFor="ca-audience" className="mb-1 block text-xs text-content-tertiary">
                        {t('agents.builder.audience_label', { defaultValue: 'Who is the answer for?' })}
                      </label>
                      <input
                        id="ca-audience"
                        type="text"
                        value={guided.audience}
                        onChange={(e) => setGuided((g) => ({ ...g, audience: e.target.value }))}
                        maxLength={200}
                        placeholder={t('agents.builder.audience_placeholder', {
                          defaultValue: 'the client / the site team',
                        })}
                        className={inputClass}
                      />
                    </div>

                    <div>
                      <label htmlFor="ca-format" className="mb-1 block text-xs text-content-tertiary">
                        {t('agents.builder.format_label', { defaultValue: 'How should it answer?' })}
                      </label>
                      <input
                        id="ca-format"
                        type="text"
                        value={guided.output_format}
                        onChange={(e) => setGuided((g) => ({ ...g, output_format: e.target.value }))}
                        maxLength={400}
                        placeholder={t('agents.builder.format_placeholder', {
                          defaultValue: 'a short formal letter / a bulleted checklist / a table',
                        })}
                        className={inputClass}
                      />
                    </div>

                    <div>
                      <label htmlFor="ca-extra" className="mb-1 block text-xs text-content-tertiary">
                        {t('agents.builder.extra_label', { defaultValue: 'Anything else to keep in mind?' })}
                      </label>
                      <input
                        id="ca-extra"
                        type="text"
                        value={guided.extra_guidance}
                        onChange={(e) => setGuided((g) => ({ ...g, extra_guidance: e.target.value }))}
                        maxLength={2000}
                        placeholder={t('agents.builder.extra_placeholder', {
                          defaultValue: 'Keep it under 200 words; always reference the contract clause.',
                        })}
                        className={inputClass}
                      />
                    </div>
                  </div>
                </div>
              </>
            )}

            {/* Example prompts */}
            <div>
              <label htmlFor="ca-examples" className="mb-1 block text-xs font-medium text-content-secondary">
                {t('agents.builder.examples_label', { defaultValue: 'Example prompts (optional)' })}
              </label>
              <textarea
                id="ca-examples"
                value={examplesText}
                onChange={(e) => setExamplesText(e.target.value)}
                rows={3}
                placeholder={t('agents.builder.examples_placeholder', {
                  defaultValue: 'One per line. These appear as one-click starters on the card.',
                })}
                className={inputClass}
              />
            </div>

            {/* Schedule (Item 29) — collapsible automation section */}
            <div className="border-t border-border-light pt-3">
              <button
                type="button"
                onClick={() => setScheduleOpen((v) => !v)}
                className="flex w-full items-center gap-1.5 text-xs font-medium text-content-secondary hover:text-content-primary"
                aria-expanded={scheduleOpen}
              >
                <ChevronDown
                  className={clsx('h-3.5 w-3.5 transition-transform', scheduleOpen && 'rotate-180')}
                  aria-hidden="true"
                />
                <Clock className="h-3.5 w-3.5 text-oe-blue" aria-hidden="true" />
                {t('agents.builder.schedule_section', { defaultValue: 'Schedule (run automatically)' })}
                {schedule.cron && (
                  <span className="ml-auto rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs font-medium text-oe-blue-text">
                    {t('agents.builder.scheduled_badge', { defaultValue: 'On' })}
                  </span>
                )}
              </button>
              {scheduleOpen && (
                <div className="mt-2">
                  {loadingAutomation ? (
                    <p className="text-xs text-content-tertiary">
                      {t('agents.builder.loading_automation', { defaultValue: 'Loading…' })}
                    </p>
                  ) : (
                    <SchedulePanel
                      cron={schedule.cron}
                      enabled={schedule.enabled}
                      scheduleInput={schedule.scheduleInput}
                      nextRunAt={initialNextRunAt}
                      onChange={setSchedule}
                    />
                  )}
                </div>
              )}
            </div>

            {/* Tools (Item 29) — collapsible tool-grant section */}
            <div className="border-t border-border-light pt-3">
              <button
                type="button"
                onClick={() => setToolsOpen((v) => !v)}
                className="flex w-full items-center gap-1.5 text-xs font-medium text-content-secondary hover:text-content-primary"
                aria-expanded={toolsOpen}
              >
                <ChevronDown
                  className={clsx('h-3.5 w-3.5 transition-transform', toolsOpen && 'rotate-180')}
                  aria-hidden="true"
                />
                <Wrench className="h-3.5 w-3.5 text-oe-blue" aria-hidden="true" />
                {t('agents.builder.tools_section', { defaultValue: 'Tools (let it read your data)' })}
                {selectedTools.length > 0 && (
                  <span className="ml-auto rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs font-medium text-oe-blue-text">
                    {selectedTools.length}
                  </span>
                )}
              </button>
              {toolsOpen && (
                <div className="mt-2">
                  <ToolPanel
                    tools={tools}
                    selected={selectedTools}
                    onChange={setSelectedTools}
                    loading={loadingAutomation}
                  />
                </div>
              )}
            </div>

            {/* Triggers (Item 29) — collapsible event-subscription section */}
            <div className="border-t border-border-light pt-3">
              <button
                type="button"
                onClick={() => setTriggersOpen((v) => !v)}
                className="flex w-full items-center gap-1.5 text-xs font-medium text-content-secondary hover:text-content-primary"
                aria-expanded={triggersOpen}
              >
                <ChevronDown
                  className={clsx('h-3.5 w-3.5 transition-transform', triggersOpen && 'rotate-180')}
                  aria-hidden="true"
                />
                <Zap className="h-3.5 w-3.5 text-oe-blue" aria-hidden="true" />
                {t('agents.builder.triggers_section', { defaultValue: 'Triggers (run on an event)' })}
                {selectedTriggers.length > 0 && (
                  <span className="ml-auto rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs font-medium text-oe-blue-text">
                    {selectedTriggers.length}
                  </span>
                )}
              </button>
              {triggersOpen && (
                <div className="mt-2">
                  <TriggerPanel
                    triggers={triggerCatalogue}
                    selected={selectedTriggers}
                    onChange={setSelectedTriggers}
                    loading={loadingAutomation}
                  />
                </div>
              )}
            </div>

            {/* Advanced: raw prompt escape hatch */}
            <div className="border-t border-border-light pt-3">
              <button
                type="button"
                onClick={() => setAdvancedOpen((v) => !v)}
                className="flex items-center gap-1 text-xs font-medium text-content-tertiary hover:text-content-secondary"
                aria-expanded={advancedOpen}
              >
                <ChevronDown
                  className={clsx('h-3.5 w-3.5 transition-transform', advancedOpen && 'rotate-180')}
                  aria-hidden="true"
                />
                {t('agents.builder.advanced_toggle', { defaultValue: 'Advanced: write the prompt yourself' })}
              </button>
              {advancedOpen && (
                <div className="mt-2">
                  <textarea
                    id="ca-raw"
                    value={rawPrompt}
                    onChange={(e) => setRawPrompt(e.target.value)}
                    rows={5}
                    maxLength={8000}
                    placeholder={t('agents.builder.advanced_placeholder', {
                      defaultValue:
                        'You are an expert … (this replaces the guided answers above when filled in).',
                    })}
                    className={inputClass}
                  />
                  <p className="mt-1 text-2xs text-content-tertiary">
                    {t('agents.builder.advanced_hint', {
                      defaultValue: 'Leave this empty to use the guided answers above.',
                    })}
                  </p>
                </div>
              )}
            </div>

            {error && (
              <div className="rounded-md bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error">
                {error}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-border-light px-6 py-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm font-medium text-content-secondary transition-colors hover:bg-surface-secondary"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className={clsx(
                'inline-flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-content-inverse transition-all',
                'hover:bg-oe-blue-hover disabled:cursor-not-allowed disabled:opacity-40',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
              )}
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              {editing
                ? t('agents.builder.save', { defaultValue: 'Save changes' })
                : t('agents.builder.create', { defaultValue: 'Create agent' })}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default CustomAgentBuilder;
