// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// AI Estimate Builder — conversational intake v2 (panel orchestrator).
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The conversational intake panel for /ai-estimate. A single vague sentence
// ("ремонт кухни 8 м2") becomes a confirmed parameter sheet and an editable,
// vector-grounded group board, through at most three clarification rounds.
//
// Two-column layout: left is the dialogue (AI chat questions or, when the
// backend says AI is unavailable, the SAME curated questions as a plain form);
// right is the live parameter sheet, then the editable group board. Every
// AI proposal is human-confirmed at two explicit checkpoints before any rate
// is matched.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, Button, Badge, Skeleton } from '@/shared/ui';
import {
  Sparkles,
  MessageSquare,
  ClipboardList,
  AlertCircle,
  RotateCcw,
  ArrowRight,
  SkipForward,
  X,
} from 'lucide-react';
import { useIntake } from './useIntake';
import { QuestionControl } from './QuestionControl';
import { ParameterSheet } from './ParameterSheet';
import { GroupBoard } from './GroupBoard';
import {
  deriveRoundView,
  serializeAnswers,
  unansweredRequired,
  seedDraftFromQuestions,
  isOfflineMode,
  isFinalRound,
  degradedMessage,
  typeConfidenceLabel,
  MAX_INTAKE_ROUNDS,
} from './helpers';
import type { IntakeCreate, IntakeState } from './types';

interface IntakePanelProps {
  projectId: string;
  /** Prefilled free-text request (from the page's description textarea). */
  initialText?: string;
  /** Pre-selected config the user picked on the page (optional). */
  region?: string;
  currency?: string;
  /** Called when the board is confirmed and the run bridges to grouping. */
  onFinished?: (runId: string) => void;
  /** Close / collapse the panel (returns to the plain text estimate flow). */
  onClose?: () => void;
}

export function IntakePanel({
  projectId,
  initialText,
  region,
  currency,
  onFinished,
  onClose,
}: IntakePanelProps) {
  const { t } = useTranslation();
  const intake = useIntake();
  const { state, pending, error } = intake;

  const [text, setText] = useState(initialText ?? '');
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [sheetParams, setSheetParams] = useState<Record<string, unknown>>({});
  // Force the curated form even when AI is available ("I'd rather fill a form").
  const [preferForm, setPreferForm] = useState(false);

  const round = useMemo(() => deriveRoundView(state), [state]);
  const offline = isOfflineMode(state) || preferForm;

  // Seed the answer draft whenever a new question batch arrives.
  useEffect(() => {
    if (round.questions.length > 0) {
      setDraft(seedDraftFromQuestions(round.questions));
    }
  }, [round.questions]);

  // Mirror confirmed params into the editable sheet on entry to checkpoint A.
  useEffect(() => {
    if (state?.phase === 'parameter_sheet') {
      setSheetParams({ ...(state.params ?? {}) });
    }
  }, [state?.phase, state?.params]);

  // ── Actions ────────────────────────────────────────────────────────────────
  const handleStart = useCallback(
    async (modeHint?: 'ai' | 'offline') => {
      if (!projectId) return;
      const body: IntakeCreate = {
        project_id: projectId,
        text: text.trim(),
        ...(modeHint ? { mode_hint: modeHint } : {}),
        ...(region ? { region } : {}),
        ...(currency ? { currency } : {}),
      };
      await intake.start(body);
    },
    [projectId, text, region, currency, intake],
  );

  const handleAnswer = useCallback(
    async (advance: boolean) => {
      if (!state) return;
      const answers = serializeAnswers(round.questions, draft);
      await intake.answer({ answers, advance });
    },
    [state, round.questions, draft, intake],
  );

  const handleSkipToEstimate = useCallback(async () => {
    if (!state) return;
    // Skip the remaining dialogue: persist whatever the user typed, then keep
    // advancing until the FSM leaves the clarify rounds. The server caps at 3
    // rounds and fills any still-missing required param with a clearly-labelled
    // default on the sheet, so this terminates fast (at most 3 advances).
    let answers = serializeAnswers(round.questions, draft);
    let next = await intake.answer({ answers, advance: true });
    let guard = 0;
    while (
      next &&
      (next.phase === 'clarify_round_1' ||
        next.phase === 'clarify_round_2' ||
        next.phase === 'clarify_round_3') &&
      guard < MAX_INTAKE_ROUNDS
    ) {
      answers = {};
      next = await intake.answer({ answers, advance: true });
      guard += 1;
    }
  }, [state, round.questions, draft, intake]);

  const handleConfirmParameters = useCallback(async () => {
    if (!state) return;
    await intake.confirmParameters({ params: sheetParams });
  }, [state, sheetParams, intake]);

  const handleFinish = useCallback(async () => {
    if (!state) return;
    const run = await intake.finish();
    if (run) onFinished?.(state.run_id);
  }, [state, intake, onFinished]);

  // Esc closes the panel (keyboard support).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && onClose) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const missing = unansweredRequired(round.questions, draft);
  const canAdvance = missing.length === 0;
  const finalRound = isFinalRound(state);

  // ── Collect-request (no run yet) ────────────────────────────────────────────
  if (!state) {
    return (
      <Card className="border-violet-200/60">
        <CardContent>
          <div className="flex items-center gap-2">
            <Sparkles size={18} className="text-violet-500" />
            <h3 className="text-base font-semibold text-content-primary">
              {t('aiest.intake.title', { defaultValue: 'Guided estimate' })}
            </h3>
            <Badge variant="blue" size="sm">
              {t('aiest.intake.beta', { defaultValue: 'Conversational' })}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-content-secondary">
            {t('aiest.intake.subtitle', {
              defaultValue:
                'Describe the job in one line. We ask a few quick questions, then build vector-grounded work packages you confirm before any rates are matched.',
            })}
          </p>
          <label htmlFor="aiest-intake-text" className="sr-only">
            {t('aiest.intake.request_label', { defaultValue: 'Project request' })}
          </label>
          <textarea
            id="aiest-intake-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void handleStart();
              }
            }}
            rows={3}
            placeholder={t('aiest.intake.request_placeholder', {
              defaultValue: 'e.g. kitchen renovation 8 m2, standard finish, replace plumbing',
            })}
            className="mt-3 w-full rounded-xl border border-border bg-surface-primary px-4 py-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
          {error && <ErrorNote message={error} onRetry={() => void handleStart()} />}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              size="md"
              loading={pending === 'start'}
              onClick={() => void handleStart()}
              disabled={!projectId}
              icon={<ArrowRight size={15} />}
              iconPosition="right"
            >
              {t('aiest.intake.start', { defaultValue: 'Start guided estimate' })}
            </Button>
            <Button
              variant="ghost"
              size="md"
              onClick={() => void handleStart('offline')}
              disabled={!projectId || pending === 'start'}
              icon={<ClipboardList size={15} />}
            >
              {t('aiest.intake.use_form', { defaultValue: "I'd rather fill a form" })}
            </Button>
            {onClose && (
              <Button variant="ghost" size="md" onClick={onClose}>
                {t('aiest.intake.cancel', { defaultValue: 'Cancel' })}
              </Button>
            )}
          </div>
          {!projectId && (
            <p className="mt-2 text-xs text-content-tertiary">
              {t('aiest.intake.need_project', {
                defaultValue: 'Select a project first to start a guided estimate.',
              })}
            </p>
          )}
        </CardContent>
      </Card>
    );
  }

  // ── Active intake (run exists) ──────────────────────────────────────────────
  const degraded = degradedMessage(state.degraded_reason);
  const typeConf = typeConfidenceLabel(state.type_confidence);

  return (
    <Card>
      <CardContent>
        {/* Header: detected type + round counter + close. */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-violet-500" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('aiest.intake.title', { defaultValue: 'Guided estimate' })}
            </h3>
            {state.detected_type && (
              <Badge variant="blue" size="sm">
                {t(`aiest.ptype.${state.detected_type}`, { defaultValue: state.detected_type })}
                <span className="ml-1 opacity-70">
                  {typeConf.i18nKey
                    ? t(typeConf.i18nKey, { defaultValue: typeConf.defaultValue })
                    : typeConf.defaultValue}
                </span>
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            {round.inRound && (
              <Badge variant="neutral" size="sm">
                {t('aiest.intake.round_counter', {
                  defaultValue: 'Round {{current}} of up to {{max}}',
                  current: round.roundNumber,
                  max: round.maxRounds,
                })}
              </Badge>
            )}
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                aria-label={t('aiest.intake.close', { defaultValue: 'Close guided estimate' })}
                className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
              >
                <X size={16} />
              </button>
            )}
          </div>
        </div>

        {degraded && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-[#92400e] dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            {t(degraded.i18nKey, { defaultValue: degraded.defaultValue })}
          </div>
        )}

        {error && <ErrorNote message={error} onRetry={() => void intake.refresh()} />}

        {/* Two-column body. */}
        <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          {/* Left: dialogue / questionnaire. */}
          <div className="min-w-0">
            {round.isWorking && <WorkingSkeleton offline={offline} />}

            {round.inRound && round.questions.length > 0 && (
              <div className="space-y-4">
                <div className="flex items-center gap-2 text-sm font-medium text-content-secondary">
                  {offline ? <ClipboardList size={15} /> : <MessageSquare size={15} />}
                  {offline
                    ? t('aiest.intake.form_heading', {
                        defaultValue: 'Answer these to compute quantities',
                      })
                    : t('aiest.intake.chat_heading', { defaultValue: 'A few quick questions' })}
                </div>

                {state.summary && (
                  <p className="rounded-lg bg-surface-secondary/60 px-3 py-2 text-sm text-content-secondary">
                    {state.summary}
                  </p>
                )}

                <div className="space-y-4">
                  {round.questions.map((q) => (
                    <QuestionControl
                      key={q.param_key}
                      question={q}
                      value={draft[q.param_key]}
                      onChange={(v) => setDraft((d) => ({ ...d, [q.param_key]: v }))}
                      disabled={pending === 'answer'}
                    />
                  ))}
                </div>

                {!canAdvance && (
                  <p className="text-xs text-content-tertiary">
                    {t('aiest.intake.missing_required', {
                      defaultValue: 'Answer the required questions (*) to continue, or skip to the estimate.',
                    })}
                  </p>
                )}

                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Button
                    variant="primary"
                    size="md"
                    loading={pending === 'answer'}
                    disabled={!canAdvance}
                    onClick={() => void handleAnswer(true)}
                    icon={<ArrowRight size={15} />}
                    iconPosition="right"
                  >
                    {finalRound
                      ? t('aiest.intake.build', { defaultValue: 'Build estimate' })
                      : t('aiest.intake.continue', { defaultValue: 'Continue' })}
                  </Button>
                  <Button
                    variant="ghost"
                    size="md"
                    onClick={() => void handleSkipToEstimate()}
                    disabled={pending === 'answer'}
                    icon={<SkipForward size={15} />}
                  >
                    {t('aiest.intake.skip', { defaultValue: 'Skip to estimate' })}
                  </Button>
                  {!offline && state.ai_connected && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setPreferForm(true)}
                      icon={<ClipboardList size={14} />}
                    >
                      {t('aiest.intake.use_form', { defaultValue: "I'd rather fill a form" })}
                    </Button>
                  )}
                </div>
              </div>
            )}

            {round.onParameterSheet && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-content-secondary">
                  <ClipboardList size={15} />
                  {t('aiest.intake.sheet_heading', {
                    defaultValue: 'Confirm the parameters',
                  })}
                </div>
                {state.summary && (
                  <p className="rounded-lg bg-surface-secondary/60 px-3 py-2 text-sm text-content-secondary">
                    {state.summary}
                  </p>
                )}
                <p className="text-sm text-content-secondary">
                  {t('aiest.intake.sheet_body', {
                    defaultValue:
                      'These drive every quantity. Edit any value on the right, then confirm. Nothing is priced until you confirm the work packages.',
                  })}
                </p>
              </div>
            )}

            {round.onGroupBoard && (
              <GroupBoard
                state={state}
                onEditPackages={(body) => void intake.editPackages(body)}
                onFinish={() => void handleFinish()}
                busy={pending === 'packages'}
                finishing={pending === 'finish'}
              />
            )}
          </div>

          {/* Right: live parameter sheet / board context. */}
          <aside className="min-w-0 lg:border-l lg:border-border lg:pl-5">
            {round.onGroupBoard ? (
              <ParameterSheet state={state} editable={false} />
            ) : (
              <ParameterSheet
                state={round.onParameterSheet ? { ...state, params: sheetParams } : state}
                editable={round.onParameterSheet}
                onChangeParam={(key, value) =>
                  setSheetParams((p) => ({ ...p, [key]: value }))
                }
                onConfirm={() => void handleConfirmParameters()}
                confirming={pending === 'confirm-parameters'}
              />
            )}
          </aside>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function WorkingSkeleton({ offline }: { offline: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <p className="text-sm text-content-secondary">
        {offline
          ? t('aiest.intake.building', { defaultValue: 'Building the questionnaire...' })
          : t('aiest.intake.thinking', { defaultValue: 'Reading your request...' })}
      </p>
      <Skeleton className="h-5 w-2/3" />
      <Skeleton className="h-9 w-40" />
      <Skeleton className="h-5 w-1/2" />
      <Skeleton className="h-9 w-40" />
    </div>
  );
}

function ErrorNote({ message, onRetry }: { message: string; onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="mt-3 flex items-start gap-2 rounded-lg border border-semantic-error/40 bg-semantic-error-bg px-3 py-2">
      <AlertCircle size={14} className="mt-0.5 shrink-0 text-semantic-error" />
      <div className="flex-1 text-xs text-semantic-error">{message}</div>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium text-semantic-error hover:bg-semantic-error/10"
      >
        <RotateCcw size={12} />
        {t('aiest.intake.retry', { defaultValue: 'Retry' })}
      </button>
    </div>
  );
}

export type { IntakeState };
