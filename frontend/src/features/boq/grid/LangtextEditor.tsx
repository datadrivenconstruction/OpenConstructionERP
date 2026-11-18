// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Side panel to edit the Kurztext and Langtext of one BOQ row.
 *
 * Opens from the pencil on a description cell, a double-click on a Langtext,
 * the row and section context menus, or Alt+L on the focused row. Positions and
 * section headers share it (a section's Kurztext is its title). Saving goes
 * through the grid's normal update path, so it lands on the undo stack.
 *
 * Keys: Ctrl+Enter saves and closes, Alt+Up / Alt+Down save and move to the
 * previous or next row, Enter in the Kurztext jumps to the Langtext.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronUp } from 'lucide-react';

import { Button, SideDrawer } from '@/shared/ui';
import { GAEB_SHORT_TEXT_MAX, getGaebLongText } from './longText';

export interface LangtextEditorRow {
  id: string;
  ordinal: string;
  description: string;
  metadata?: Record<string, unknown> | null;
  isSection: boolean;
}

export interface LangtextTexts {
  description: string;
  long_text: string;
}

export interface LangtextEditorProps {
  row: LangtextEditorRow | null;
  /** Field that takes the caret when the panel opens. */
  focus: 'short' | 'long';
  readOnly: boolean;
  hasPrev: boolean;
  hasNext: boolean;
  onNavigate: (dir: -1 | 1) => void;
  onSave: (id: string, next: LangtextTexts, old: LangtextTexts) => void;
  onClose: () => void;
}

function textsOf(row: LangtextEditorRow | null): LangtextTexts {
  return {
    description: row?.description ?? '',
    long_text: getGaebLongText(row?.metadata) ?? '',
  };
}

export function LangtextEditor({
  row,
  focus,
  readOnly,
  hasPrev,
  hasNext,
  onNavigate,
  onSave,
  onClose,
}: LangtextEditorProps) {
  const { t } = useTranslation();
  const original = textsOf(row);
  const [shortDraft, setShortDraft] = useState(original.description);
  const [longDraft, setLongDraft] = useState(original.long_text);
  const shortRef = useRef<HTMLTextAreaElement>(null);
  const longRef = useRef<HTMLTextAreaElement>(null);
  const rowId = row?.id ?? null;

  // A new row (open or Alt+Up/Down) starts from its stored texts.
  useEffect(() => {
    const fresh = textsOf(row);
    setShortDraft(fresh.description);
    setLongDraft(fresh.long_text);
    // Only the row identity resets the drafts; a refetch of the same row must
    // not throw away what is being typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowId]);

  useEffect(() => {
    if (!rowId) return;
    const id = window.setTimeout(() => {
      const el = focus === 'long' ? longRef.current : shortRef.current;
      el?.focus();
      if (el && focus === 'long') el.setSelectionRange(el.value.length, el.value.length);
    }, 60);
    return () => window.clearTimeout(id);
  }, [rowId, focus]);

  const trimmedShort = shortDraft.trim();
  const dirty =
    !readOnly &&
    (trimmedShort !== original.description.trim() || longDraft.trim() !== original.long_text.trim());
  const canSave = dirty && (trimmedShort.length > 0 || Boolean(row?.isSection));

  const save = useCallback((): boolean => {
    if (!row || !canSave) return !dirty;
    onSave(
      row.id,
      { description: trimmedShort, long_text: longDraft.replace(/\r\n?/g, '\n').trim() },
      original,
    );
    return true;
  }, [row, canSave, dirty, onSave, trimmedShort, longDraft, original]);

  const discard = () => {
    setShortDraft(original.description);
    setLongDraft(original.long_text);
  };

  const navigate = (dir: -1 | 1) => {
    if ((dir < 0 && !hasPrev) || (dir > 0 && !hasNext)) return;
    if (save()) onNavigate(dir);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    // Keep grid-level shortcuts (undo, delete, copy) out of the panel.
    e.stopPropagation();
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      if (save()) onClose();
    } else if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      navigate(e.key === 'ArrowUp' ? -1 : 1);
    }
  };

  const shortLen = trimmedShort.length;
  const shortOver = !row?.isSection && shortLen > GAEB_SHORT_TEXT_MAX;
  const longLines = longDraft ? longDraft.split('\n').length : 0;

  const title = row?.isSection
    ? t('boq.text_editor_title_section', { defaultValue: 'Section title and Langtext' })
    : t('boq.text_editor_title', { defaultValue: 'Kurztext and Langtext' });
  const fieldCls =
    'w-full rounded-lg border bg-surface-primary px-3 py-2 text-sm text-content-primary ' +
    'placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue ' +
    'read-only:bg-surface-secondary';

  return (
    <SideDrawer
      open={row !== null}
      onClose={onClose}
      title={title}
      subtitle={row?.ordinal ? `${t('boq.ordinal', { defaultValue: 'Pos.' })} ${row.ordinal}` : undefined}
      widthClass="sm:max-w-2xl"
      // Unsaved text is never dropped by a stray Escape or backdrop click.
      busy={dirty}
      backdropCloses={!dirty}
      headerActions={
        <>
          <button
            type="button"
            onClick={() => navigate(-1)}
            disabled={!hasPrev}
            title={`${t('boq.text_editor_prev', { defaultValue: 'Previous row' })} (Alt+↑)`}
            aria-label={t('boq.text_editor_prev', { defaultValue: 'Previous row' })}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary hover:text-content-primary disabled:opacity-40 disabled:pointer-events-none"
          >
            <ChevronUp size={16} />
          </button>
          <button
            type="button"
            onClick={() => navigate(1)}
            disabled={!hasNext}
            title={`${t('boq.text_editor_next', { defaultValue: 'Next row' })} (Alt+↓)`}
            aria-label={t('boq.text_editor_next', { defaultValue: 'Next row' })}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary hover:text-content-primary disabled:opacity-40 disabled:pointer-events-none"
          >
            <ChevronDown size={16} />
          </button>
        </>
      }
    >
      <div className="flex min-h-[calc(100%-57px)] flex-col" onKeyDown={onKeyDown} data-testid="boq-text-editor">
        <div className="flex-1 space-y-4 px-4 py-4">
          {readOnly && (
            <p className="rounded-lg bg-surface-secondary px-3 py-2 text-xs text-content-secondary">
              {t('boq.text_editor_read_only', { defaultValue: 'This bill is locked; the texts can be read but not changed.' })}
            </p>
          )}
          <div>
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <label htmlFor="boq-text-editor-short" className="text-sm font-semibold text-content-primary">
                {row?.isSection
                  ? t('boq.text_editor_section_title', { defaultValue: 'Title' })
                  : t('boq.text_editor_short', { defaultValue: 'Kurztext' })}
              </label>
              {!row?.isSection && (
                <span
                  className={`text-xs tabular-nums ${shortOver ? 'font-semibold text-semantic-warning' : 'text-content-tertiary'}`}
                  data-testid="boq-text-editor-short-count"
                >
                  {shortLen} / {GAEB_SHORT_TEXT_MAX}
                </span>
              )}
            </div>
            <textarea
              id="boq-text-editor-short"
              ref={shortRef}
              rows={2}
              value={shortDraft}
              readOnly={readOnly}
              onChange={(e) => setShortDraft(e.target.value)}
              onKeyDown={(e) => {
                // A Kurztext is one line: Enter moves on to the Langtext.
                if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
                  e.preventDefault();
                  longRef.current?.focus();
                }
              }}
              className={`${fieldCls} resize-none font-medium ${shortOver ? 'border-semantic-warning' : 'border-border'}`}
            />
            <p className={`mt-1 text-xs ${shortOver ? 'text-semantic-warning' : 'text-content-tertiary'}`}>
              {shortOver
                ? t('boq.text_editor_short_over', {
                    defaultValue: 'GAEB export cuts the Kurztext to {{max}} characters. Move the details into the Langtext.',
                    max: GAEB_SHORT_TEXT_MAX,
                  })
                : t('boq.text_editor_short_hint', {
                    defaultValue: 'One line that names the work. It appears in every list, printout and export.',
                  })}
            </p>
          </div>
          <div className="flex flex-col">
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <label htmlFor="boq-text-editor-long" className="text-sm font-semibold text-content-primary">
                {t('boq.text_editor_long', { defaultValue: 'Langtext' })}
              </label>
              <span className="text-xs tabular-nums text-content-tertiary">
                {t('boq.text_editor_long_count', {
                  defaultValue: '{{lines}} lines, {{chars}} characters',
                  lines: longLines,
                  chars: longDraft.length,
                })}
              </span>
            </div>
            <textarea
              id="boq-text-editor-long"
              ref={longRef}
              value={longDraft}
              readOnly={readOnly}
              onChange={(e) => setLongDraft(e.target.value)}
              placeholder={t('boq.text_editor_long_placeholder', {
                defaultValue: 'No Langtext yet. Type or paste the full description of the work here.',
              })}
              spellCheck
              className={`${fieldCls} min-h-[45vh] resize-y border-border leading-6`}
              data-testid="boq-text-editor-long"
            />
            <p className="mt-1 text-xs text-content-tertiary">
              {t('boq.text_editor_long_hint', {
                defaultValue: 'The full description. Line breaks are kept; it is printed under the Kurztext and exported as the GAEB Langtext.',
              })}
            </p>
          </div>
        </div>
        <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t border-border-light bg-surface-elevated px-4 py-3">
          <span className="mr-auto text-xs text-content-tertiary">
            {dirty
              ? t('boq.text_editor_unsaved', { defaultValue: 'Unsaved changes' })
              : t('boq.text_editor_keys', { defaultValue: 'Ctrl+Enter saves. Alt+Up / Alt+Down moves to the previous or next row.' })}
          </span>
          {dirty && (
            <Button variant="ghost" size="sm" onClick={discard}>
              {t('boq.text_editor_discard', { defaultValue: 'Discard changes' })}
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={onClose} disabled={dirty}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          {!readOnly && (
            <Button
              variant="primary"
              size="sm"
              disabled={!canSave}
              onClick={() => {
                if (save()) onClose();
              }}
              data-testid="boq-text-editor-save"
            >
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
          )}
        </div>
      </div>
    </SideDrawer>
  );
}
