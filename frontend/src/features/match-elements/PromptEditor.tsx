// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Prompt editor for the LLM-augmented pipeline stages.
//
// System prompts (is_system) are read-only — the user must Fork them
// into a private, editable copy. Forking copies the wording verbatim so
// the estimator starts from the proven n8n-derived baseline and tunes
// from there. The editor surfaces the ``{placeholder}`` variables the
// stage runner fills so the user does not break the contract by
// renaming one.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { GitFork, Loader2, RotateCcw, Save, Sparkles } from 'lucide-react';

import { matchElementsApi, type PromptTemplate } from './api';

interface Props {
  /** Stage hook key, e.g. ``match.cost_agent``. */
  promptKey: string;
  /** Currently selected template id (from the stage row), or null. */
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/** Pull every ``{name}`` token out of a template body so the user can
 *  see which variables the stage runner injects. ``{{`` / ``}}`` are
 *  literal braces (str.format escape) and are skipped. */
function extractVars(body: string): string[] {
  const out = new Set<string>();
  const re = /(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(body)) !== null) {
    if (m[1]) out.add(m[1]);
  }
  return [...out];
}

export function PromptEditor({ promptKey, selectedId, onSelect }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const listQ = useQuery({
    queryKey: ['match-prompt-templates', promptKey],
    queryFn: () => matchElementsApi.listPromptTemplates(promptKey),
  });

  const templates = listQ.data ?? [];
  const active: PromptTemplate | undefined = useMemo(() => {
    if (selectedId) return templates.find((x) => x.id === selectedId);
    // Default: newest user prompt, else the system prompt.
    const user = templates.filter((x) => !x.is_system);
    if (user.length) return user[0];
    return templates.find((x) => x.is_system) ?? templates[0];
  }, [templates, selectedId]);

  const [sys, setSys] = useState('');
  const [usr, setUsr] = useState('');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (active) {
      setSys(active.system_prompt);
      setUsr(active.user_template);
      setDirty(false);
    }
  }, [active?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const vars = useMemo(() => extractVars(usr), [usr]);

  const forkMut = useMutation({
    mutationFn: () =>
      matchElementsApi.createPromptTemplate({
        key: promptKey,
        name: `${active?.name ?? 'Prompt'} (my copy)`,
        description: active?.description ?? null,
        system_prompt: sys,
        user_template: usr,
        forked_from_id: active?.id ?? null,
      }),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['match-prompt-templates', promptKey] });
      onSelect(created.id);
      setDirty(false);
    },
  });

  const saveMut = useMutation({
    mutationFn: () =>
      matchElementsApi.updatePromptTemplate(active!.id, {
        system_prompt: sys,
        user_template: usr,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['match-prompt-templates', promptKey] });
      setDirty(false);
    },
  });

  if (listQ.isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-content-tertiary py-3">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        {t('match_elements.pipeline.loading_prompts', 'Loading prompts…')}
      </div>
    );
  }

  const isSystem = !!active?.is_system;

  return (
    <div className="space-y-2.5">
      {/* Template selector */}
      <div className="flex items-center gap-2 flex-wrap">
        <label className="text-[11px] uppercase tracking-wider text-content-tertiary font-semibold">
          {t('match_elements.pipeline.prompt', 'Prompt')}
        </label>
        <select
          value={active?.id ?? ''}
          onChange={(e) => onSelect(e.target.value)}
          className="flex-1 min-w-[160px] text-xs px-2 py-1.5 rounded-lg border border-border bg-surface-primary text-content-primary"
        >
          {templates.map((tpl) => (
            <option key={tpl.id} value={tpl.id}>
              {tpl.is_system ? '★ ' : ''}
              {tpl.name} · v{tpl.version}
              {tpl.is_system
                ? ` · ${t('match_elements.pipeline.system', 'system')}`
                : ''}
            </option>
          ))}
        </select>
      </div>

      {isSystem && (
        <div className="flex items-center gap-1.5 text-[11px] text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/20 border border-amber-200/60 dark:border-amber-800/40 rounded-lg px-2 py-1.5">
          <Sparkles className="w-3 h-3 shrink-0" />
          {t(
            'match_elements.pipeline.system_readonly',
            'System prompt — read-only. Fork it to edit and tune for your company.',
          )}
        </div>
      )}

      {/* System prompt */}
      <div>
        <div className="text-[11px] uppercase tracking-wider text-content-tertiary font-semibold mb-1">
          {t('match_elements.pipeline.system_prompt', 'System prompt')}
        </div>
        <textarea
          value={sys}
          readOnly={isSystem}
          onChange={(e) => {
            setSys(e.target.value);
            setDirty(true);
          }}
          rows={3}
          className="w-full text-xs font-mono px-2.5 py-2 rounded-lg border border-border bg-surface-secondary text-content-primary resize-y disabled:opacity-60"
        />
      </div>

      {/* User template */}
      <div>
        <div className="text-[11px] uppercase tracking-wider text-content-tertiary font-semibold mb-1">
          {t('match_elements.pipeline.user_template', 'User template')}
        </div>
        <textarea
          value={usr}
          readOnly={isSystem}
          onChange={(e) => {
            setUsr(e.target.value);
            setDirty(true);
          }}
          rows={8}
          className="w-full text-xs font-mono px-2.5 py-2 rounded-lg border border-border bg-surface-secondary text-content-primary resize-y disabled:opacity-60"
        />
      </div>

      {/* Variables contract */}
      {vars.length > 0 && (
        <div className="flex items-start gap-1.5 flex-wrap text-[11px] text-content-tertiary">
          <span className="font-semibold">
            {t('match_elements.pipeline.variables', 'Variables the stage fills:')}
          </span>
          {vars.map((v) => (
            <code
              key={v}
              className="px-1.5 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950/30 text-indigo-700 dark:text-indigo-300 border border-indigo-200/60 dark:border-indigo-800/40"
            >
              {`{${v}}`}
            </code>
          ))}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        {isSystem ? (
          <button
            onClick={() => forkMut.mutate()}
            disabled={forkMut.isPending}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-oe-blue text-white hover:opacity-90 disabled:opacity-50"
          >
            {forkMut.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <GitFork className="w-3 h-3" />
            )}
            {t('match_elements.pipeline.fork', 'Fork to edit')}
          </button>
        ) : (
          <>
            <button
              onClick={() => saveMut.mutate()}
              disabled={!dirty || saveMut.isPending}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-oe-blue text-white hover:opacity-90 disabled:opacity-40"
            >
              {saveMut.isPending ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Save className="w-3 h-3" />
              )}
              {t('match_elements.pipeline.save_prompt', 'Save prompt')}
            </button>
            {dirty && (
              <button
                onClick={() => {
                  if (active) {
                    setSys(active.system_prompt);
                    setUsr(active.user_template);
                    setDirty(false);
                  }
                }}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-border text-content-secondary hover:bg-surface-secondary"
              >
                <RotateCcw className="w-3 h-3" />
                {t('match_elements.pipeline.revert', 'Revert')}
              </button>
            )}
            <button
              onClick={() => forkMut.mutate()}
              disabled={forkMut.isPending}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-border text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
            >
              <GitFork className="w-3 h-3" />
              {t('match_elements.pipeline.duplicate', 'Duplicate')}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
