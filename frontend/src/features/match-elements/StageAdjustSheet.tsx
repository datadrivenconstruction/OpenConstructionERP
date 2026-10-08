// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Slide-over "Adjust" panel for one pipeline stage.
//
// Shows the plain-language explainer, the per-stage knobs (group keys,
// match method/caps, threshold...), the editable LLM prompt (for the
// three LLM-augmented stages), the LLM provider picker, and the
// "Re-run from here" CTA. Running a stage marks every downstream
// done-stage stale so the user always sees what still needs a re-run.

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Play, Sparkles, X } from 'lucide-react';

import {
  matchElementsApi,
  LLM_PROVIDERS,
  type StageState,
} from './api';
import { PromptEditor } from './PromptEditor';

interface Props {
  sessionId: string;
  stage: StageState;
  /** True when another stage is already running — Re-run is gated on
   *  this so two stages can't race the same session. */
  busy: boolean;
  onClose: () => void;
  onRan: () => void;
}

export function StageAdjustSheet({
  sessionId,
  stage,
  busy,
  onClose,
  onRan,
}: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  // ── Per-stage knobs ───────────────────────────────────────────────
  // Seed group-by from the stage's own override if it has one, else
  // from what the Group stage actually used (its recorded output) so
  // the field shows the *current effective* keys instead of looking
  // empty and silently re-running with no change.
  const [groupBy, setGroupBy] = useState<string>(() => {
    const fromInputs = (stage.inputs as { group_by?: unknown }).group_by;
    if (Array.isArray(fromInputs) && fromInputs.length > 0) {
      return fromInputs.map(String).join(', ');
    }
    const fromOutput = (stage.output as { group_by?: unknown }).group_by;
    if (Array.isArray(fromOutput) && fromOutput.length > 0) {
      return fromOutput.map(String).join(', ');
    }
    return '';
  });
  const [method, setMethod] = useState<string>(
    String((stage.inputs as { method?: string }).method ?? 'vector'),
  );
  const [maxGroups, setMaxGroups] = useState<number>(
    Number((stage.inputs as { max_groups?: number }).max_groups ?? 50),
  );
  const [topK, setTopK] = useState<number>(
    Number((stage.inputs as { top_k?: number }).top_k ?? 10),
  );

  const [promptId, setPromptId] = useState<string | null>(
    stage.prompt_template_id,
  );
  const [provider, setProvider] = useState<string>(
    stage.llm_provider ?? LLM_PROVIDERS[0]?.id ?? 'anthropic/claude-sonnet-4-6',
  );

  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    // Remember what had focus (the stage card's Adjust button) so we
    // can hand it back when the slide-over closes.
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // A focused native <select> uses Escape for its own dropdown —
        // don't also tear down the sheet in that case.
        if ((e.target as HTMLElement)?.tagName === 'SELECT') return;
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const root = panelRef.current;
      if (!root) return;
      const f = Array.from(
        root.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
        // ``offsetParent`` is null for descendants of a position:fixed
        // panel (this one), so use rect presence as the visibility test.
      ).filter(
        (el) => el.getClientRects().length > 0 || el === document.activeElement,
      );
      if (f.length === 0) return;
      const first = f[0]!;
      const last = f[f.length - 1]!;
      const act = document.activeElement as HTMLElement | null;
      if (e.shiftKey) {
        if (act === first || !root.contains(act)) {
          e.preventDefault();
          last.focus();
        }
      } else if (act === last || !root.contains(act)) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey, true);
    // Move focus into the slide-over so keyboard / SR users are not
    // stranded on the page behind it.
    panelRef.current?.focus();
    const returnTo = returnFocusRef.current;
    return () => {
      window.removeEventListener('keydown', onKey, true);
      if (returnTo && typeof returnTo.focus === 'function') {
        requestAnimationFrame(() => returnTo.focus());
      }
    };
  }, [onClose]);

  const runMut = useMutation({
    mutationFn: () => {
      const inputs: Record<string, unknown> = { ...stage.inputs };
      if (stage.stage_name === 'group') {
        inputs.group_by = groupBy
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean);
      }
      if (stage.stage_name === 'match') {
        inputs.method = method;
        inputs.max_groups = maxGroups;
        inputs.top_k = topK;
      }
      return matchElementsApi.runStage(sessionId, stage.stage_name, {
        inputs,
        prompt_template_id: stage.uses_llm ? promptId : null,
        llm_provider: stage.uses_llm ? provider : null,
      });
    },
    onSuccess: (res) => {
      // The endpoint returns HTTP 200 even when the stage itself failed
      // (``status: "error"`` in the body). Refresh the pipeline either
      // way, but only auto-close on a real success — on a stage error
      // keep the sheet open and surface the message so the user can fix
      // the knobs and retry instead of the sheet vanishing silently.
      qc.invalidateQueries({ queryKey: ['match-stages', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-session', sessionId] });
      if (res.status !== 'error') onRan();
    },
  });

  // Stage-level failure surfaced from a 200 response (vs. a transport
  // error, handled by ``runMut.isError`` below).
  const stageError =
    runMut.data?.status === 'error'
      ? runMut.data.error ??
        t('match_elements.pipeline.run_failed', 'Stage run failed')
      : null;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="stage-adjust-title"
        tabIndex={-1}
        className="fixed right-0 top-0 bottom-0 w-full max-w-md z-50 bg-surface-primary border-l border-border shadow-2xl flex flex-col outline-none"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-border">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-wider text-content-tertiary font-semibold">
              {t('match_elements.pipeline.adjust_stage', 'Adjust stage')}
            </div>
            <h2
              id="stage-adjust-title"
              className="text-base font-bold text-content-primary truncate"
            >
              {stage.title}
            </h2>
            <p className="text-xs text-content-secondary">{stage.subtitle}</p>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 p-1.5 rounded-lg hover:bg-surface-secondary text-content-tertiary"
            aria-label={t('common.close', 'Close')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {/* Explainer */}
          <p className="text-xs text-content-secondary leading-relaxed bg-surface-secondary border border-border rounded-lg px-3 py-2.5">
            {stage.explainer}
          </p>

          {/* Group-by knob */}
          {stage.stage_name === 'group' && (
            <div>
              <label className="text-[11px] uppercase tracking-wider text-content-tertiary font-semibold">
                {t('match_elements.pipeline.group_by', 'Group by keys')}
              </label>
              <input
                value={groupBy}
                onChange={(e) => setGroupBy(e.target.value)}
                placeholder="ifc_class, predefined_type"
                className="mt-1 w-full text-xs px-2.5 py-2 rounded-lg border border-border bg-surface-primary text-content-primary font-mono"
              />
              <p className="mt-1 text-[11px] text-content-tertiary">
                {t(
                  'match_elements.pipeline.group_by_hint',
                  'Comma-separated. RVT → category, type_name · IFC → ifc_class, predefined_type · DWG → layer, block_name',
                )}
              </p>
            </div>
          )}

          {/* Match knobs */}
          {stage.stage_name === 'match' && (
            <div className="space-y-3">
              <div>
                <label className="text-[11px] uppercase tracking-wider text-content-tertiary font-semibold">
                  {t('match_elements.pipeline.method', 'Method')}
                </label>
                <div className="mt-1 flex gap-1.5 flex-wrap">
                  {(['vector', 'resources', 'llm'] as const).map(
                    (m) => (
                      <button
                        key={m}
                        onClick={() => setMethod(m)}
                        className={
                          'px-2.5 py-1.5 rounded-lg text-xs font-medium border ' +
                          (method === m
                            ? 'bg-oe-blue text-white border-oe-blue'
                            : 'border-border text-content-secondary hover:bg-surface-secondary')
                        }
                      >
                        {m}
                      </button>
                    ),
                  )}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[11px] uppercase tracking-wider text-content-tertiary font-semibold">
                    {t('match_elements.pipeline.max_groups', 'Max groups')}
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={maxGroups}
                    onChange={(e) => setMaxGroups(Number(e.target.value))}
                    className="mt-1 w-full text-xs px-2.5 py-2 rounded-lg border border-border bg-surface-primary text-content-primary"
                  />
                </div>
                <div>
                  <label className="text-[11px] uppercase tracking-wider text-content-tertiary font-semibold">
                    Top-K
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={topK}
                    onChange={(e) => setTopK(Number(e.target.value))}
                    className="mt-1 w-full text-xs px-2.5 py-2 rounded-lg border border-border bg-surface-primary text-content-primary"
                  />
                </div>
              </div>
            </div>
          )}

          {/* LLM prompt + provider */}
          {stage.uses_llm && stage.prompt_key && (
            <div className="space-y-3 border-t border-border pt-3">
              <div className="flex items-start gap-1.5 text-[11px] text-content-tertiary bg-surface-secondary border border-border rounded-lg px-2.5 py-2">
                <Sparkles className="w-3 h-3 mt-0.5 shrink-0 text-indigo-500" />
                <span>
                  {t(
                    'match_elements.pipeline.llm_pending_note',
                    'This stage runs the deterministic heuristic today. Your prompt and provider are saved and versioned per session - they take effect automatically once LLM execution is enabled for this step. Tuning them now means you are ready the moment it is.',
                  )}
                </span>
              </div>
              <PromptEditor
                promptKey={stage.prompt_key}
                selectedId={promptId}
                onSelect={setPromptId}
              />
              <div>
                <label className="text-[11px] uppercase tracking-wider text-content-tertiary font-semibold">
                  {t('match_elements.pipeline.llm_provider', 'LLM provider')}
                </label>
                <div className="mt-1 grid grid-cols-1 gap-1">
                  {LLM_PROVIDERS.map((p) => (
                    <label
                      key={p.id}
                      className={
                        'flex items-center gap-2 px-2.5 py-1.5 rounded-lg border cursor-pointer text-xs ' +
                        (provider === p.id
                          ? 'border-oe-blue bg-oe-blue/5'
                          : 'border-border hover:bg-surface-secondary')
                      }
                    >
                      <input
                        type="radio"
                        name="llm-provider"
                        checked={provider === p.id}
                        onChange={() => setProvider(p.id)}
                        className="accent-oe-blue"
                      />
                      <span className="text-content-primary">{p.label}</span>
                      <code className="ml-auto text-[10px] text-content-tertiary">
                        {p.id}
                      </code>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          )}

          {(runMut.isError || stageError) && (
            <div
              role="alert"
              className="text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/20 border border-rose-200/60 dark:border-rose-800/40 rounded-lg px-3 py-2 break-words"
            >
              {runMut.isError
                ? ((runMut.error as Error)?.message ??
                  t('match_elements.pipeline.run_failed', 'Stage run failed'))
                : stageError}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-border flex items-center gap-2">
          <button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || busy}
            title={
              busy
                ? t(
                    'match_elements.pipeline.busy_hint',
                    'A stage is running - wait for it to finish before starting another.',
                  )
                : undefined
            }
            className="flex-1 inline-flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-semibold bg-oe-blue text-white hover:opacity-90 disabled:opacity-50"
          >
            {runMut.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            {t('match_elements.pipeline.rerun_from_here', 'Re-run from here')}
          </button>
          <button
            onClick={onClose}
            className="px-3 py-2.5 rounded-lg text-sm font-medium border border-border text-content-secondary hover:bg-surface-secondary"
          >
            {t('common.cancel', 'Cancel')}
          </button>
        </div>
      </div>
    </>
  );
}
