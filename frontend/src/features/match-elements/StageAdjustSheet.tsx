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

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Play, X } from 'lucide-react';

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
  const [groupBy, setGroupBy] = useState<string>(
    Array.isArray((stage.inputs as { group_by?: string[] }).group_by)
      ? ((stage.inputs as { group_by?: string[] }).group_by ?? []).join(', ')
      : '',
  );
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

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['match-stages', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-session', sessionId] });
      onRan();
    },
  });

  return (
    <>
      <div
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
        aria-hidden
      />
      <div className="fixed right-0 top-0 bottom-0 w-full max-w-md z-50 bg-surface-primary border-l border-border shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-border">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-wider text-content-tertiary font-semibold">
              {t('match_elements.pipeline.adjust_stage', 'Adjust stage')}
            </div>
            <h2 className="text-base font-bold text-content-primary truncate">
              {stage.title}
            </h2>
            <p className="text-xs text-content-secondary">{stage.subtitle}</p>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 p-1.5 rounded-lg hover:bg-surface-secondary text-content-tertiary"
            aria-label="Close"
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
                  {(['vector', 'resources', 'lexical', 'llm'] as const).map(
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

          {runMut.isError && (
            <div className="text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/20 border border-rose-200/60 dark:border-rose-800/40 rounded-lg px-3 py-2">
              {(runMut.error as Error)?.message ??
                t('match_elements.pipeline.run_failed', 'Stage run failed')}
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
                    'A stage is running — wait for it to finish before starting another.',
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
