// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Read-only YAML viewer for the NL Rule Builder. We render with a
// pre/code block plus a tiny token-level highlighter — no codemirror
// dependency.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

interface DslPreviewProps {
  yaml: string | null;
  /** Click handler for the "copy YAML" affordance. Optional. */
  onCopy?: () => void;
}

/* Match YAML keys (foo:), strings ('bar'/"bar"), and numbers. */
const TOKEN_RE = /(^[ \t]*[a-zA-Z_][a-zA-Z0-9_]*:)|('[^']*')|("[^"]*")|(\b\d+(?:\.\d+)?\b)/gm;

function highlightToken(token: string): string {
  if (token.endsWith(':')) return 'text-oe-blue font-medium';
  if (token.startsWith("'") || token.startsWith('"')) return 'text-semantic-success';
  if (/^\d/.test(token)) return 'text-semantic-warning';
  return '';
}

function renderHighlighted(yaml: string): React.ReactNode {
  const out: React.ReactNode[] = [];
  let lastIdx = 0;
  let match: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  while ((match = TOKEN_RE.exec(yaml)) !== null) {
    if (match.index > lastIdx) {
      out.push(yaml.slice(lastIdx, match.index));
    }
    const tok = match[0];
    const cls = highlightToken(tok);
    out.push(
      cls ? (
        <span key={match.index} className={cls}>
          {tok}
        </span>
      ) : (
        tok
      ),
    );
    lastIdx = match.index + tok.length;
  }
  if (lastIdx < yaml.length) {
    out.push(yaml.slice(lastIdx));
  }
  return out;
}

export function DslPreview({ yaml, onCopy }: DslPreviewProps) {
  const { t } = useTranslation();

  const highlighted = useMemo(() => {
    if (!yaml) return null;
    return renderHighlighted(yaml);
  }, [yaml]);

  return (
    <div
      className="flex h-full flex-col"
      data-testid="dsl-preview"
      aria-label={t('compliance.nl.preview_title', { defaultValue: 'DSL Preview' })}
    >
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('compliance.nl.preview_title', { defaultValue: 'DSL Preview' })}
        </h3>
        {yaml && onCopy && (
          <button
            type="button"
            onClick={onCopy}
            data-testid="dsl-preview-copy"
            className="text-xs font-medium text-oe-blue hover:underline"
          >
            {t('common.copy', { defaultValue: 'Copy' })}
          </button>
        )}
      </div>
      {yaml ? (
        <pre
          data-testid="dsl-preview-yaml"
          className="flex-1 overflow-auto rounded-lg border border-border-light bg-surface-secondary p-3 text-xs font-mono text-content-primary"
        >
          <code>{highlighted}</code>
        </pre>
      ) : (
        <div
          data-testid="dsl-preview-empty"
          className="flex-1 rounded-lg border border-dashed border-border-light p-4 text-center text-xs text-content-tertiary"
        >
          {t('compliance.nl.no_dsl_yet', {
            defaultValue: 'Type a sentence and press Generate to see the DSL.',
          })}
        </div>
      )}
    </div>
  );
}
