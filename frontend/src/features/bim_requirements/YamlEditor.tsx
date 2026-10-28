// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * YamlEditor — plain textarea + side gutter line numbers.
 *
 * Intentionally minimal: no Monaco, no CodeMirror, no syntax-highlight
 * dependency. The component renders a side-by-side gutter of line numbers
 * (a sibling `<div>` synced via shared scrollTop) next to a monospace
 * textarea. Tab inserts two spaces. An optional readonly mode disables
 * editing entirely.
 *
 * Designed for the BIM Rules Library preview/install modal — see
 * `RulePackPreviewModal` for the wiring.
 */

import { useCallback, useId, useMemo, useRef, type ChangeEvent, type KeyboardEvent, type UIEvent } from 'react';
import clsx from 'clsx';
import { AlertCircle, CheckCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export interface YamlEditorProps {
  value: string;
  onChange?: (next: string) => void;
  /** Disable editing (used when previewing a seed pack as-is). */
  readonly?: boolean;
  /** Show a side gutter with 1-indexed line numbers. Defaults to true. */
  lineNumbers?: boolean;
  /** Inline error banner shown under the textarea (e.g. parse errors). */
  error?: string | null;
  /** Render a small "parsed" badge in the top-right corner. */
  parsed?: boolean;
  /** Visible textarea rows. Defaults to 18. */
  rows?: number;
  /** Optional placeholder for the empty / custom-mode editor. */
  placeholder?: string;
  /** Optional id forwarded to the textarea (label association). */
  id?: string;
  /** data-testid for tests. Defaults to "yaml-editor". */
  testId?: string;
  /** Extra className on the wrapper. */
  className?: string;
}

const TAB_SPACES = '  ';

export function YamlEditor({
  value,
  onChange,
  readonly = false,
  lineNumbers = true,
  error,
  parsed = false,
  rows = 18,
  placeholder,
  id,
  testId = 'yaml-editor',
  className,
}: YamlEditorProps) {
  const { t } = useTranslation();
  const reactId = useId();
  const textareaId = id ?? `yaml-editor-${reactId}`;
  const gutterRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Pre-compute the line-number column. Splitting on `\n` keeps the count
  // honest even when a trailing newline is present (matches what the user
  // sees while typing).
  const lineCount = useMemo(() => {
    if (!value) return 1;
    return value.split('\n').length;
  }, [value]);

  const lineNumberLines = useMemo(() => {
    const arr: number[] = [];
    for (let i = 1; i <= lineCount; i += 1) arr.push(i);
    return arr;
  }, [lineCount]);

  const handleScroll = useCallback((event: UIEvent<HTMLTextAreaElement>) => {
    if (!gutterRef.current) return;
    gutterRef.current.scrollTop = event.currentTarget.scrollTop;
  }, []);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (readonly) return;
      if (event.key !== 'Tab') return;
      // Insert two spaces instead of letting the browser shift focus.
      event.preventDefault();
      const target = event.currentTarget;
      const start = target.selectionStart;
      const end = target.selectionEnd;
      const next = `${value.slice(0, start)}${TAB_SPACES}${value.slice(end)}`;
      onChange?.(next);
      // Restore caret position after React re-renders. We schedule on the
      // next animation frame because setting selectionStart synchronously
      // after a controlled-value change race-conditions with React.
      requestAnimationFrame(() => {
        if (textareaRef.current) {
          const caret = start + TAB_SPACES.length;
          textareaRef.current.selectionStart = caret;
          textareaRef.current.selectionEnd = caret;
        }
      });
    },
    [onChange, readonly, value],
  );

  const handleChange = useCallback(
    (event: ChangeEvent<HTMLTextAreaElement>) => {
      if (readonly) return;
      onChange?.(event.target.value);
    },
    [onChange, readonly],
  );

  return (
    <div
      className={clsx('flex flex-col gap-2', className)}
      data-testid={testId}
    >
      <div className="relative flex overflow-hidden rounded-lg border border-border-light bg-surface-primary">
        {lineNumbers && (
          <div
            ref={gutterRef}
            aria-hidden="true"
            data-testid={`${testId}-gutter`}
            className="select-none overflow-hidden bg-surface-secondary px-2 py-2 text-right font-mono text-[11px] leading-5 text-content-tertiary"
            style={{ minWidth: '2.5rem' }}
          >
            {lineNumberLines.map((n) => (
              <div key={n} data-testid={`${testId}-line-${n}`}>
                {n}
              </div>
            ))}
          </div>
        )}
        <textarea
          ref={textareaRef}
          id={textareaId}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onScroll={handleScroll}
          readOnly={readonly}
          rows={rows}
          spellCheck={false}
          placeholder={placeholder}
          data-testid={`${testId}-textarea`}
          aria-label={t('bim_requirements.yaml_editor_label', { defaultValue: 'YAML rule pack editor' })}
          aria-readonly={readonly}
          className={clsx(
            'flex-1 resize-y bg-transparent px-3 py-2 font-mono text-[12px] leading-5 text-content-primary outline-none',
            readonly && 'cursor-default text-content-secondary',
          )}
        />
        {parsed && !error && (
          <span
            data-testid={`${testId}-parsed-badge`}
            className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700"
          >
            <CheckCircle2 size={10} />
            parsed
          </span>
        )}
      </div>
      {error && (
        <div
          data-testid={`${testId}-error`}
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700"
        >
          <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
          <span className="whitespace-pre-wrap">{error}</span>
        </div>
      )}
    </div>
  );
}

export default YamlEditor;
