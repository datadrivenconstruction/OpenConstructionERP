// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "New session from text" modal — implements MAPPING_PROCESS.md §4.1.6.
// One textarea, one line per estimable item. Each non-empty line becomes
// a SourceElement; semantic search drives recall (BGE-M3 multilingual,
// recall@10 ≈ 0.97 per the v3 bench).

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, X, FileText } from 'lucide-react';
import { matchElementsApi, type MatchSession } from './api';

interface Props {
  projectId: string;
  onClose: () => void;
  onCreated: (session: MatchSession) => void;
}

export function NewSessionFromTextModal({ projectId, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [text, setText] = useState('');

  const lines = text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

  const mut = useMutation({
    mutationFn: () =>
      matchElementsApi.createSession({
        project_id: projectId,
        source: 'text',
        name: name.trim() || undefined,
        text_inputs: lines,
      }),
    onSuccess: (session) => {
      qc.invalidateQueries({ queryKey: ['match-sessions', projectId] });
      onCreated(session);
    },
  });

  const canSubmit = lines.length > 0 && !mut.isPending;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-xl bg-surface-primary shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-oe-blue" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t(
                'match_elements.new_text.title',
                'New session - paste descriptions',
              )}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-content-tertiary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <p className="text-xs text-content-tertiary leading-relaxed">
            {t(
              'match_elements.new_text.hint',
              'One line per item. Each line becomes a group; semantic search finds the closest CWICR rates. Use any language - the multilingual encoder handles cross-lang queries.',
            )}
          </p>

          <div>
            <label
              htmlFor="me-text-name"
              className="block text-xs font-medium text-content-secondary mb-1"
            >
              {t('match_elements.new_text.name_label', 'Session name (optional)')}
            </label>
            <input
              id="me-text-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t(
                'match_elements.new_text.name_placeholder',
                'e.g. Quick estimate Q3',
              )}
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-1.5 text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
          </div>

          <div>
            <label
              htmlFor="me-text-input"
              className="block text-xs font-medium text-content-secondary mb-1"
            >
              {t(
                'match_elements.new_text.lines_label',
                'Descriptions (one per line)',
              )}
              <span className="ml-2 tabular-nums text-content-quaternary">
                {lines.length}
              </span>
            </label>
            <textarea
              id="me-text-input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={10}
              spellCheck={false}
              placeholder={t(
                'match_elements.new_text.lines_placeholder',
                'Stahlbetonwand C30/37, d=240mm\nленточный фундамент 800x600\nconcrete slab 200mm',
              )}
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm font-mono text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 resize-y"
            />
          </div>

          {mut.isError && (
            <div className="rounded border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:border-rose-700 dark:bg-rose-900/30 dark:text-rose-200">
              {String((mut.error as Error)?.message ?? mut.error)}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light bg-surface-secondary/50">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-content-secondary hover:text-content-primary"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={() => mut.mutate()}
            disabled={!canSubmit}
            className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-oe-blue/90 disabled:opacity-50"
          >
            {mut.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {t('match_elements.new_text.create', 'Create session')}
          </button>
        </div>
      </div>
    </div>
  );
}
