interface ProjectInfo {
  id?: string;
  name?: string;
  code?: string;
  region?: string;
  currency?: string;
  contract_value?: number;
  status?: string;
}

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  active: { bg: 'rgba(63, 185, 80, 0.15)', text: 'var(--chat-tool-done)' },
  planning: { bg: 'rgba(56, 139, 253, 0.15)', text: 'var(--chat-tool-running)' },
  completed: { bg: 'rgba(139, 148, 158, 0.15)', text: 'var(--chat-text-secondary)' },
  on_hold: { bg: 'rgba(240, 136, 62, 0.15)', text: 'var(--chat-accent)' },
  cancelled: { bg: 'rgba(248, 81, 73, 0.15)', text: 'var(--chat-tool-error)' },
};

function formatCurrency(value: number | undefined, currency?: string): string {
  if (value == null) return '-';
  const formatted = value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return currency ? `${formatted} ${currency}` : formatted;
}

export default function ProjectsGridRenderer({ data }: { data: unknown }) {
  const projects: ProjectInfo[] = Array.isArray(data) ? data : [];

  if (projects.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        No projects found
      </div>
    );
  }

  return (
    <div
      style={{
        overflow: 'auto',
        height: '100%',
        padding: 12,
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
        gap: 10,
        alignContent: 'start',
      }}
    >
      {projects.map((p, i) => {
        const statusStyle = STATUS_COLORS[p.status ?? ''] ?? STATUS_COLORS.active;
        return (
          <div
            key={p.id ?? i}
            style={{
              background: 'var(--chat-surface-1)',
              border: '1px solid var(--chat-border-subtle)',
              borderRadius: 'var(--chat-radius)',
              padding: 14,
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--chat-text-primary)', fontFamily: 'var(--chat-font-body)' }}>
                  {p.name ?? 'Untitled'}
                </div>
                {p.code && (
                  <div style={{ fontSize: 12, fontFamily: 'var(--chat-font-mono)', color: 'var(--chat-text-tertiary)', marginTop: 2 }}>
                    {p.code}
                  </div>
                )}
              </div>
              {p.status && (
                <span
                  style={{
                    padding: '2px 8px',
                    fontSize: 11,
                    fontFamily: 'var(--chat-font-mono)',
                    fontWeight: 500,
                    borderRadius: 10,
                    background: statusStyle?.bg,
                    color: statusStyle?.text,
                    textTransform: 'uppercase',
                    letterSpacing: '0.03em',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {p.status}
                </span>
              )}
            </div>
            {p.region && (
              <div style={{ fontSize: 12, color: 'var(--chat-text-secondary)', fontFamily: 'var(--chat-font-body)' }}>
                {p.region}
              </div>
            )}
            <div
              style={{
                fontSize: 18,
                fontWeight: 700,
                fontFamily: 'var(--chat-font-mono)',
                color: 'var(--chat-accent)',
                marginTop: 'auto',
              }}
            >
              {formatCurrency(p.contract_value, p.currency)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
