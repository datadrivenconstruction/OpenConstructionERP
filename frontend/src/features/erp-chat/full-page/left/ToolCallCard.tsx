import { useState } from 'react';
import type { ToolCallInfo } from '../../types';

const TOOL_LABELS: Record<string, string> = {
  get_all_projects: 'All projects',
  get_boq_items: 'BOQ items',
  get_schedule: 'Schedule',
  get_validation_results: 'Validation results',
  get_risk_register: 'Risk register',
  search_cwicr_database: 'CWICR search',
  get_cost_model: 'Cost model',
  compare_projects: 'Project comparison',
  get_project_summary: 'Project summary',
  run_validation: 'Run validation',
  create_boq_item: 'Create BOQ item',
  match_boq_prices_cwicr: 'Match prices',
  generate_schedule_from_boq: 'Generate schedule',
};

function formatDuration(ms: number | undefined): string {
  if (ms === undefined) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
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
  const [expanded, setExpanded] = useState(false);
  const label = TOOL_LABELS[tool.name] ?? tool.name;

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
          textAlign: 'left',
          fontFamily: 'inherit',
          fontSize: 'inherit',
        }}
      >
        <StatusIcon status={tool.status} />
        <span style={{ color: 'var(--chat-accent)', fontWeight: 500 }}>{label}</span>
        {tool.result?.summary && (
          <span
            style={{
              color: 'var(--chat-text-secondary)',
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {tool.result.summary}
          </span>
        )}
        {tool.durationMs !== undefined && (
          <span style={{ color: 'var(--chat-text-tertiary)', fontFamily: 'var(--chat-font-mono)', fontSize: 11, flexShrink: 0 }}>
            {formatDuration(tool.durationMs)}
          </span>
        )}
        <span
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
              <div style={{ color: 'var(--chat-text-tertiary)', fontSize: 10, marginBottom: 2 }}>INPUT</div>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {JSON.stringify(tool.input, null, 2)}
              </pre>
            </div>
          )}
          {tool.result?.data !== undefined && (
            <div>
              <div style={{ color: 'var(--chat-text-tertiary)', fontSize: 10, marginBottom: 2 }}>OUTPUT</div>
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
