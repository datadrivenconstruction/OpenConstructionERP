// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What the dock shows before the first message: one sentence that says what
 * the assistant is for, the three steps every change goes through, and
 * example prompts to start from.
 *
 * The examples come in two kinds. "Do" examples are instructions: the
 * assistant answers them with a proposal card, and nothing is written until
 * someone applies it. "Ask" examples are questions it answers from the
 * project data. Examples for the current page come first (their testids are
 * `ctx-*` and they sit under `floating-chat-contextual-label`), then the ones
 * that work anywhere (`generic-*`); inside each block the Do examples come
 * before the Ask ones. The e2e onboarding spec pins that order, the six
 * generic examples, and the accommodation page's occupancy question in first
 * place (that page has nothing to change, so it has no Do examples).
 *
 * There used to be a lock on examples that "looked like" writes (an English
 * verb prefix such as "create " or "add ") for anyone below manager. It came
 * from the time the chat wrote to the project directly. Now every write is a
 * proposal, applying it re-runs the record's own REST gates for the person
 * who clicks Apply, and the prefix match never worked on translated text
 * anyway, so every example is open to everyone.
 */
import { useId, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowRight, MessageCircleQuestion, PenLine, ShieldCheck } from 'lucide-react';
import clsx from 'clsx';

export type SuggestionKind = 'do' | 'ask';

export interface PageSuggestions {
  do: string[];
  ask: string[];
}

/** Examples that make sense on any page, Do first. Six, as the e2e spec expects. */
function useGenericSuggestions(): PageSuggestions {
  const { t } = useTranslation();
  return useMemo(
    () => ({
      do: [t('chat.panel.sugg_draft_rfi', { defaultValue: 'Create a draft RFI from the latest clash' })],
      ask: [
        t('chat.panel.sugg_over_budget', { defaultValue: 'What are my over-budget projects?' }),
        t('chat.panel.sugg_top_risks', { defaultValue: 'Show me top open risks' }),
        t('chat.panel.sugg_walls', { defaultValue: "Find all walls > 30cm in current project's BIM" }),
        t('chat.panel.sugg_validate_boq', { defaultValue: 'Validate the current BOQ' }),
        t('chat.panel.sugg_critical_path', { defaultValue: "What's the schedule critical path?" }),
      ],
    }),
    [t],
  );
}

/**
 * Examples tuned to the page the person is on, matched on the path prefix
 * only (no params), so `/boq/abc` and any future `/boq/abc/...` route share
 * them. Empty on pages without a bundle; the dock then shows only the
 * examples that work anywhere.
 */
export function usePageSuggestions(pathname: string): PageSuggestions {
  const { t } = useTranslation();
  return useMemo(() => {
    const createTask = () =>
      t('chat.panel.do.create_task', {
        defaultValue: 'Add a task for the site team: check the formwork on level 3 by Friday',
      });
    const logRisk = () => t('chat.panel.do.log_risk', { defaultValue: 'Log a risk: late steel delivery, high impact' });
    const raiseRfi = () =>
      t('chat.panel.do.raise_rfi', { defaultValue: 'Raise an RFI: which reinforcement goes into the level 3 slab?' });

    if (/^\/boq\/[^/]+/.test(pathname)) {
      return {
        do: [
          t('chat.panel.do.add_position', {
            defaultValue: 'Add a position: 120 m3 of C30/37 concrete for the level 3 slab',
          }),
          t('chat.panel.do.change_quantity', { defaultValue: 'Change the quantity of the first position to 120' }),
        ],
        ask: [
          t('chat.panel.ctx_boq.validate', { defaultValue: 'Validate this BOQ' }),
          t('chat.panel.ctx_boq.suggest_missing', { defaultValue: 'Suggest cost items for missing positions' }),
          t('chat.panel.ctx_boq.compare', { defaultValue: 'Compare this BOQ against my other projects' }),
        ],
      };
    }
    if (/^\/projects\/[^/]+/.test(pathname)) {
      return {
        do: [createTask(), logRisk(), raiseRfi()],
        ask: [
          t('chat.panel.ctx_project.summary', { defaultValue: "Summarize this project's status" }),
          t('chat.panel.ctx_project.open_risks', { defaultValue: "Show me this project's open risks" }),
          t('chat.panel.ctx_project.over_budget', { defaultValue: 'What are the over-budget areas?' }),
        ],
      };
    }
    if (/^\/schedule(\/|$)/.test(pathname)) {
      return {
        do: [
          t('chat.panel.do.set_progress', {
            defaultValue: 'Set the progress of the first activity in the schedule to 60%',
          }),
        ],
        ask: [t('chat.panel.ask_schedule.behind', { defaultValue: 'Which activities are behind schedule?' })],
      };
    }
    if (/^\/tasks(\/|$)/.test(pathname)) return { do: [createTask()], ask: [] };
    if (/^\/rfi(\/|$)/.test(pathname)) return { do: [raiseRfi()], ask: [] };
    if (/^\/risks(\/|$)/.test(pathname)) return { do: [logRisk()], ask: [] };
    if (/^\/punchlist(\/|$)/.test(pathname)) {
      return {
        do: [t('chat.panel.do.punch_item', { defaultValue: 'Add a punch item: cracked tile in the level 2 lobby' })],
        ask: [],
      };
    }
    if (/^\/accommodation\/[^/]+/.test(pathname)) {
      return {
        do: [],
        ask: [
          t('chat.panel.ctx_accommodation.occupancy', { defaultValue: 'Show me occupancy trend' }),
          t('chat.panel.ctx_accommodation.suggest_room', {
            defaultValue: 'Suggest a room for the next arriving employee',
          }),
          t('chat.panel.ctx_accommodation.bookings_ending', { defaultValue: 'List bookings ending this week' }),
        ],
      };
    }
    if (/^\/geo(\/|$)/.test(pathname)) {
      return {
        do: [],
        ask: [
          t('chat.panel.ctx_geo.nearby', { defaultValue: 'Find projects within 50 km of my current view' }),
          t('chat.panel.ctx_geo.clashes', { defaultValue: 'Show me clashes on the active project' }),
        ],
      };
    }
    if (/^\/bim(\/|$)/.test(pathname)) {
      return {
        do: [],
        ask: [
          t('chat.panel.ctx_bim.unlinked', { defaultValue: 'List unlinked elements in this model' }),
          t('chat.panel.ctx_bim.compare_revisions', { defaultValue: 'Compare quantities between revisions' }),
        ],
      };
    }
    return { do: [], ask: [] };
    // `t` keeps a stable identity per language, so this re-derives on a route
    // change or a language switch only.
  }, [pathname, t]);
}

function SuggestionChip({
  text,
  kind,
  onPick,
  testIdSuffix,
}: {
  text: string;
  kind: SuggestionKind;
  onPick: (text: string) => void;
  testIdSuffix: string;
}) {
  const Icon = kind === 'do' ? PenLine : MessageCircleQuestion;
  return (
    <button
      type="button"
      onClick={() => onPick(text)}
      data-testid={`floating-chat-suggestion-${testIdSuffix}`}
      data-kind={kind}
      className={clsx(
        'group flex w-full items-start gap-2 rounded-lg border px-3 py-2 text-start text-[13px] leading-snug transition-colors',
        'border-[color:var(--chat-border-subtle)] bg-[color:var(--chat-surface-2)] text-[color:var(--chat-text-primary)]',
        'hover:border-[color:var(--chat-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
      )}
    >
      <Icon
        size={14}
        aria-hidden
        className={clsx(
          'mt-0.5 shrink-0',
          kind === 'do' ? 'text-[color:var(--chat-accent)]' : 'text-[color:var(--chat-text-tertiary)]',
        )}
      />
      <span className="min-w-0 flex-1">{text}</span>
    </button>
  );
}

/** One kind of example ("Do" or "Ask") with its own small heading. */
function SuggestionGroup({
  kind,
  items,
  onPick,
  testIdPrefix,
  offset,
}: {
  kind: SuggestionKind;
  items: string[];
  onPick: (text: string) => void;
  testIdPrefix: 'ctx' | 'generic';
  /** Index of the first chip, so testids keep counting across the two groups. */
  offset: number;
}) {
  const { t } = useTranslation();
  const headingId = useId();
  if (items.length === 0) return null;
  const Icon = kind === 'do' ? PenLine : MessageCircleQuestion;
  return (
    <div role="group" aria-labelledby={headingId} className="flex flex-col gap-2">
      <div
        id={headingId}
        className="flex items-center gap-1.5 text-xs font-medium text-[color:var(--chat-text-secondary)]"
      >
        <Icon size={12} aria-hidden />
        {kind === 'do'
          ? t('chat.panel.group_do', { defaultValue: 'Do: I prepare the change, you approve it' })
          : t('chat.panel.group_ask', { defaultValue: 'Ask: I look it up in your data' })}
      </div>
      {items.map((text, i) => (
        <SuggestionChip
          key={`${kind}-${text}`}
          text={text}
          kind={kind}
          onPick={onPick}
          testIdSuffix={`${testIdPrefix}-${offset + i}`}
        />
      ))}
    </div>
  );
}

const SCOPE_LABEL = 'text-[11px] font-semibold uppercase tracking-wide text-[color:var(--chat-text-tertiary)]';

export function DockEmptyState({ onPick, pathname }: { onPick: (text: string) => void; pathname: string }) {
  const { t } = useTranslation();
  const generic = useGenericSuggestions();
  const page = usePageSuggestions(pathname);
  const hasPage = page.do.length + page.ask.length > 0;
  const steps = [
    t('chat.panel.step_ask', { defaultValue: 'Ask' }),
    t('chat.panel.step_review', { defaultValue: 'Review' }),
    t('chat.panel.step_apply', { defaultValue: 'Apply' }),
  ];

  return (
    <div className="flex flex-col gap-4 px-4 py-4" data-testid="floating-chat-empty-state">
      <div className="flex flex-col gap-3">
        <p className="text-[15px] font-semibold leading-snug text-[color:var(--chat-text-primary)]">
          {t('chat.panel.empty_lead', {
            defaultValue: 'Tell me what to do. I prepare the changes, you approve them.',
          })}
        </p>
        <div className="rounded-lg border border-[color:var(--chat-border-subtle)] bg-[color:var(--chat-surface-1)] px-3 py-2">
          <ol
            aria-label={t('chat.panel.steps_label', { defaultValue: 'How a change is made' })}
            className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs font-medium text-[color:var(--chat-text-primary)]"
          >
            {steps.map((step, i) => (
              <li key={i} className="flex items-center gap-1.5">
                {i > 0 && (
                  <ArrowRight
                    size={12}
                    aria-hidden
                    className="shrink-0 text-[color:var(--chat-text-tertiary)] rtl:-scale-x-100"
                  />
                )}
                <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[color:var(--chat-accent)] text-[10px] font-semibold leading-none text-white tabular-nums">
                  {i + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
          <p className="mt-1.5 flex items-start gap-1.5 text-xs leading-snug text-[color:var(--chat-text-secondary)]">
            <ShieldCheck size={13} aria-hidden className="mt-px shrink-0 text-[color:var(--chat-tool-done)]" />
            {t('chat.panel.steps_logged', {
              defaultValue: 'Nothing is saved until you apply it, and every change is logged.',
            })}
          </p>
        </div>
      </div>

      {hasPage && (
        <div className="flex flex-col gap-2">
          <div className={SCOPE_LABEL} data-testid="floating-chat-contextual-label">
            {t('chat.panel.contextual_label', { defaultValue: 'For this page' })}
          </div>
          <div className="flex flex-col gap-3" data-testid="floating-chat-contextual-chips">
            <SuggestionGroup kind="do" items={page.do} onPick={onPick} testIdPrefix="ctx" offset={0} />
            <SuggestionGroup kind="ask" items={page.ask} onPick={onPick} testIdPrefix="ctx" offset={page.do.length} />
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2">
        {hasPage && (
          <div className={clsx(SCOPE_LABEL, 'border-t border-[color:var(--chat-border-subtle)] pt-4')}>
            {t('chat.panel.generic_label', { defaultValue: 'Anywhere' })}
          </div>
        )}
        <div className="flex flex-col gap-3">
          <SuggestionGroup kind="do" items={generic.do} onPick={onPick} testIdPrefix="generic" offset={0} />
          <SuggestionGroup
            kind="ask"
            items={generic.ask}
            onPick={onPick}
            testIdPrefix="generic"
            offset={generic.do.length}
          />
        </div>
      </div>
    </div>
  );
}
