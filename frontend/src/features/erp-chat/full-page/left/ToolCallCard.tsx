// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ToolCallInfo } from '../../types';
import { isProposalTool, toolLabel, toolRefusalText } from '../../toolLabels';
import { RENDERER_REGISTRY } from '../right/renderers';
import { fmtFixed } from '@/shared/lib/formatters';

function formatDuration(ms: number | undefined): string {
  if (ms === undefined) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${fmtFixed(ms / 1000, 1)}s`;
}

function StatusIcon({ status }: { status: ToolCallInfo['status'] }) {
  if (status === 'running') {
    return (
      <span
        style={{
          display: 'inline-block',
          width: 14,
          height: 14,
          border: '2px solid var(--chat-tool-running)',
          borderTopColor: 'transparent',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }}
      />
    );
  }
  if (status === 'done') {
    return <span style={{ color: 'var(--chat-tool-done)', fontSize: 14, lineHeight: 1 }}>&#10003;</span>;
  }
  return <span style={{ color: 'var(--chat-tool-error)', fontSize: 14, lineHeight: 1 }}>&#10007;</span>;
}

export default function ToolCallCard({ tool }: { tool: ToolCallInfo }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  // A prepared change is shown as its card, with Apply / Edit / Reject, the
  // same card as in the dock. It is the answer, not a detail to expand, and
  // its raw payload is no use to the reader.
  const ProposalCard = RENDERER_REGISTRY.action_proposal;
  if (tool.result?.renderer === 'action_proposal' && ProposalCard && tool.result.data !== undefined) {
    return (
      <div style={{ marginBottom: 6 }}>
        <ProposalCard data={tool.result.data} />
      </div>
    );
  }

  const proposal = isProposalTool(tool.name);
  const name = toolLabel(tool.name, t);
  const label =
    proposal && tool.status === 'running'
      ? t('erp_chat.tool.preparing', { defaultValue: 'Preparing a change: {{label}}…', label: name })
      : proposal && tool.status === 'error'
        ? t('erp_chat.tool.not_prepared', { defaultValue: 'Change not prepared: {{label}}', label: name })
        : name;
  // A refused proposal's summary is written for the model ("fix the
  // arguments, then call the tool again"); the reader gets the reason.
  const summary =
    proposal && tool.status === 'error'
      ? toolRefusalText(tool.result?.data, t) ?? undefined
      : tool.result?.summary;

  return (
    <div
      style={{
        background: 'var(--chat-surface-1)',
        border: '1px solid var(--chat-border-subtle)',
        borderRadius: 'var(--chat-radius-sm)',
        marginBottom: 6,
        fontSize: 13,
        fontFamily: 'var(--chat-font-body)',
        overflow: 'hidden',
      }}
    >
      {/* inline style for spin animation */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          width: '100%',
          padding: '8px 10px',
          background: 'none',
          border: 'none',
          color: 'var(--chat-text-primary)',
          cursor: 'pointer',
          textAlign: 'start',
          fontFamily: 'inherit',
          fontSize: 'inherit',
        }}
      >
        <StatusIcon status={tool.status} />
        <span style={{ color: 'var(--chat-accent)', fontWeight: 500 }}>{label}</span>
        {summary && (
          <span
            style={{
              color: 'var(--chat-text-secondary)',
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={summary}
          >
            {summary}
          </span>
        )}
        {tool.durationMs !== undefined && (
          <span style={{ color: 'var(--chat-text-tertiary)', fontFamily: 'var(--chat-font-mono)', fontSize: 11, flexShrink: 0 }}>
            {formatDuration(tool.durationMs)}
          </span>
        )}
        <span
          aria-hidden
          style={{
            color: 'var(--chat-text-tertiary)',
            fontSize: 10,
            transition: 'transform 0.15s',
            transform: expanded ? 'rotate(180deg)' : 'none',
            flexShrink: 0,
          }}
        >
          &#9660;
        </span>
      </button>

      {expanded && (
        <div
          style={{
            borderTop: '1px solid var(--chat-border-subtle)',
            padding: '8px 10px',
            fontFamily: 'var(--chat-font-mono)',
            fontSize: 11,
            lineHeight: 1.5,
            color: 'var(--chat-text-secondary)',
            maxHeight: 200,
            overflow: 'auto',
          }}
        >
          {tool.input && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ color: 'var(--chat-text-tertiary)', fontSize: 10, marginBottom: 2 }}>
                {t('chat.tool_input', { defaultValue: 'INPUT' })}
              </div>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {JSON.stringify(tool.input, null, 2)}
              </pre>
            </div>
          )}
          {tool.result?.data !== undefined && (
            <div>
              <div style={{ color: 'var(--chat-text-tertiary)', fontSize: 10, marginBottom: 2 }}>
                {t('chat.tool_output', { defaultValue: 'OUTPUT' })}
              </div>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {JSON.stringify(tool.result.data, null, 2).slice(0, 2000)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
