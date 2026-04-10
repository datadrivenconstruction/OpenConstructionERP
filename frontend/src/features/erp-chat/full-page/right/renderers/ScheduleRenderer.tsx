interface Activity {
  name?: string;
  start?: string | number;
  end?: string | number;
  duration_days?: number;
  is_critical?: boolean;
}

function parseDayOffset(val: string | number | undefined, minDate: number): number {
  if (val == null) return 0;
  if (typeof val === 'number') return val;
  const ms = new Date(val).getTime();
  if (isNaN(ms)) return 0;
  return Math.round((ms - minDate) / (1000 * 60 * 60 * 24));
}

export default function ScheduleRenderer({ data }: { data: unknown }) {
  const activities: Activity[] = Array.isArray(data) ? data : [];

  if (activities.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        No schedule data available
      </div>
    );
  }

  // Determine if data uses date strings or day offsets
  const hasDateStrings = activities.some(
    (a) => typeof a.start === 'string' && !isNaN(new Date(a.start).getTime()),
  );

  let minDay = 0;
  let maxDay = 1;

  if (hasDateStrings) {
    const dates = activities.flatMap((a) => {
      const vals: number[] = [];
      if (typeof a.start === 'string') {
        const ms = new Date(a.start).getTime();
        if (!isNaN(ms)) vals.push(ms);
      }
      if (typeof a.end === 'string') {
        const ms = new Date(a.end).getTime();
        if (!isNaN(ms)) vals.push(ms);
      }
      return vals;
    });
    const minDate = Math.min(...dates);
    const maxDate = Math.max(...dates);
    minDay = 0;
    maxDay = Math.max(1, Math.round((maxDate - minDate) / (1000 * 60 * 60 * 24)));

    // Rewrite start/end as day offsets
    for (const a of activities) {
      (a as Record<string, unknown>)._startDay = parseDayOffset(a.start, minDate);
      (a as Record<string, unknown>)._endDay = parseDayOffset(a.end, minDate);
    }
  } else {
    for (const a of activities) {
      const s = typeof a.start === 'number' ? a.start : 0;
      const e = typeof a.end === 'number' ? a.end : s + (a.duration_days ?? 1);
      (a as Record<string, unknown>)._startDay = s;
      (a as Record<string, unknown>)._endDay = e;
      if (s < minDay) minDay = s;
      if (e > maxDay) maxDay = e;
    }
  }

  const range = maxDay - minDay || 1;
  const criticalCount = activities.filter((a) => a.is_critical).length;

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 12, fontFamily: 'var(--chat-font-body)' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {activities.map((a, i) => {
          const s = ((a as Record<string, unknown>)._startDay as number) ?? 0;
          const e = ((a as Record<string, unknown>)._endDay as number) ?? s + 1;
          const leftPct = ((s - minDay) / range) * 100;
          const widthPct = Math.max(((e - s) / range) * 100, 1);
          const color = a.is_critical ? 'var(--chat-accent)' : 'var(--chat-tool-running)';

          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                minHeight: 28,
              }}
            >
              <div
                style={{
                  width: 140,
                  flexShrink: 0,
                  fontSize: 12,
                  color: 'var(--chat-text-secondary)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
                title={a.name}
              >
                {a.name ?? `Activity ${i + 1}`}
              </div>
              <div
                style={{
                  flex: 1,
                  position: 'relative',
                  height: 18,
                  background: 'var(--chat-surface-1)',
                  borderRadius: 3,
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    position: 'absolute',
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    height: '100%',
                    background: color,
                    borderRadius: 3,
                    minWidth: 4,
                    opacity: 0.85,
                  }}
                />
              </div>
              <div
                style={{
                  width: 40,
                  flexShrink: 0,
                  fontSize: 11,
                  fontFamily: 'var(--chat-font-mono)',
                  color: 'var(--chat-text-tertiary)',
                  textAlign: 'right',
                }}
              >
                {Math.round(e - s)}d
              </div>
            </div>
          );
        })}
      </div>
      <div
        style={{
          marginTop: 12,
          paddingTop: 10,
          borderTop: '1px solid var(--chat-border-subtle)',
          fontSize: 12,
          color: 'var(--chat-text-secondary)',
          fontFamily: 'var(--chat-font-mono)',
        }}
      >
        {activities.length} activities &middot; {Math.round(range)} days total
        {criticalCount > 0 && (
          <span style={{ color: 'var(--chat-accent)' }}>
            {' '}&middot; {criticalCount} critical path
          </span>
        )}
      </div>
    </div>
  );
}
