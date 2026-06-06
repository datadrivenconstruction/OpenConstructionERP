import { toNum } from './normalize';
import { projectPath } from './deepLink';
import DeepLinkBar, { useOpenLabels } from './DeepLinkBar';

/**
 * Renders the `project_summary` tool result (`get_project_summary`):
 * a single project's budget, schedule dates, status and description.
 */
interface ProjectSummary {
  id?: string;
  name?: string;
  code?: string;
  status?: string;
  region?: string;
  currency?: string;
  contract_value?: number | string;
  budget_estimate?: number | string;
  phase?: string;
  project_type?: string;
  planned_start_date?: string;
  planned_end_date?: string;
  actual_start_date?: string;
  actual_end_date?: string;
  description?: string;
}

function money(v: number | string | undefined, currency?: string): string {
  const n = toNum(v);
  if (n == null) return '-';
  const f = n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return currency ? `${f} ${currency}` : f;
}

function dateOrDash(s: string | undefined): string {
  if (!s || s === 'None' || s === '') return '-';
  return s.slice(0, 10);
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span
        style={{
          fontSize: 11,
          fontFamily: 'var(--chat-font-mono)',
          color: 'var(--chat-text-tertiary)',
          textTransform: 'uppercase',
          letterSpacing: '0.03em',
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 13, color: 'var(--chat-text-primary)' }}>{value}</span>
    </div>
  );
}

export default function ProjectSummaryRenderer({ data }: { data: unknown }) {
  const labels = useOpenLabels();
  const p = (data && typeof data === 'object' && !Array.isArray(data) ? data : {}) as ProjectSummary;

  if (!p.name && !p.id) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        No project summary available
      </div>
    );
  }

  const cur = p.currency || undefined;

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 16, fontFamily: 'var(--chat-font-body)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--chat-text-primary)' }}>{p.name ?? 'Project'}</div>
          {p.code && (
            <div style={{ fontSize: 12, fontFamily: 'var(--chat-font-mono)', color: 'var(--chat-text-tertiary)', marginTop: 2 }}>
              {p.code}
            </div>
          )}
        </div>
        {p.status && (
          <span
            style={{
              padding: '3px 10px',
              fontSize: 11,
              fontFamily: 'var(--chat-font-mono)',
              borderRadius: 12,
              background: 'var(--chat-surface-2)',
              color: 'var(--chat-accent)',
              textTransform: 'uppercase',
              whiteSpace: 'nowrap',
            }}
          >
            {p.status}
          </span>
        )}
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
          gap: 14,
          background: 'var(--chat-surface-1)',
          border: '1px solid var(--chat-border-subtle)',
          borderRadius: 'var(--chat-radius)',
          padding: 16,
        }}
      >
        <Field label="Contract value" value={money(p.contract_value, cur)} />
        <Field label="Budget estimate" value={money(p.budget_estimate, cur)} />
        {p.phase && <Field label="Phase" value={p.phase} />}
        {p.project_type && <Field label="Type" value={p.project_type} />}
        {p.region && <Field label="Region" value={p.region} />}
        <Field label="Planned start" value={dateOrDash(p.planned_start_date)} />
        <Field label="Planned end" value={dateOrDash(p.planned_end_date)} />
        <Field label="Actual start" value={dateOrDash(p.actual_start_date)} />
        <Field label="Actual end" value={dateOrDash(p.actual_end_date)} />
      </div>

      {p.description && (
        <div style={{ marginTop: 14, fontSize: 13, lineHeight: 1.6, color: 'var(--chat-text-secondary)' }}>
          {p.description}
        </div>
      )}

      {projectPath(p.id) && <DeepLinkBar to={projectPath(p.id)!} label={labels.project} />}
    </div>
  );
}
