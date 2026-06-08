/**
 * T8 — ERP-Chat admin observability dashboard.
 *
 * Mirrors construction management platform AI admin views:
 * token spend, prompt-cache hit rate, thumbs feedback rate, top thumbed-down
 * prompts, and a per-day breakdown — all gated behind the manager+
 * `erp_chat.admin` permission server-side.
 */

import { useEffect, useMemo, useState } from 'react';
import { ThumbsUp, ThumbsDown, Cpu, Database, Activity } from 'lucide-react';
import { getAdminStats } from './api';
import type { AdminStats } from './types';

const WINDOWS = [7, 30, 90] as const;

interface StatCardProps {
  label: string;
  value: string;
  icon: React.ReactNode;
  sub?: string;
}

function StatCard({ label, value, icon, sub }: StatCardProps) {
  return (
    <div
      style={{
        // 90% translucent surface (no blur) so the page dot grid shows
        // through faintly, matching the canonical StatCard look.
        background: 'color-mix(in srgb, var(--chat-surface-1, #fff) 90%, transparent)',
        border: '1px solid var(--chat-border, #e5e7eb)',
        borderRadius: 12,
        padding: '14px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        minWidth: 0,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          color: 'var(--chat-text-secondary, #6b7280)',
          fontSize: 12,
          fontWeight: 500,
          letterSpacing: 0.2,
          textTransform: 'uppercase',
        }}
      >
        <span>{label}</span>
        <span style={{ display: 'inline-flex', opacity: 0.6 }}>{icon}</span>
      </div>
      <div
        style={{
          fontSize: 24,
          fontWeight: 700,
          color: 'var(--chat-text-primary, #111827)',
          fontVariantNumeric: 'tabular-nums',
          lineHeight: 1.1,
        }}
      >
        {value}
      </div>
      {sub && (
        <div
          style={{
            fontSize: 12,
            color: 'var(--chat-text-tertiary, #9ca3af)',
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

export default function AdminStatsPage() {
  const [windowDays, setWindowDays] = useState<number>(30);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getAdminStats(windowDays)
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg.includes('403') ? 'Manager role required to view this page.' : msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [windowDays]);

  // Pre-compute a scale for the chart bars so the tallest column fits.
  const dailyMax = useMemo(() => {
    if (!stats) return 1;
    return Math.max(1, ...stats.daily_breakdown.map((d) => d.messages));
  }, [stats]);

  return (
    <div
      style={{
        padding: '24px 28px',
        maxWidth: 1100,
        margin: '0 auto',
        fontFamily: 'var(--chat-font-body, system-ui, sans-serif)',
        color: 'var(--chat-text-primary, #111827)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
          marginBottom: 20,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>
            Chat observability
          </h1>
          <p
            style={{
              margin: '4px 0 0',
              color: 'var(--chat-text-secondary, #6b7280)',
              fontSize: 13,
            }}
          >
            Token spend, thumbs feedback, and prompt-cache hit rate for the AI
            assistant.
          </p>
        </div>
        <div
          role="group"
          aria-label="Time window"
          style={{
            display: 'inline-flex',
            background: 'var(--chat-surface-1, #fff)',
            border: '1px solid var(--chat-border, #e5e7eb)',
            borderRadius: 10,
            padding: 2,
          }}
        >
          {WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => setWindowDays(w)}
              style={{
                padding: '6px 14px',
                border: 'none',
                background:
                  windowDays === w
                    ? 'var(--chat-accent, #3b82f6)'
                    : 'transparent',
                color:
                  windowDays === w
                    ? '#fff'
                    : 'var(--chat-text-secondary, #6b7280)',
                borderRadius: 8,
                fontWeight: 600,
                fontSize: 12,
                cursor: 'pointer',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {w}d
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div
          style={{
            padding: '14px 16px',
            background: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: 10,
            color: '#991b1b',
            fontSize: 13,
            marginBottom: 16,
          }}
        >
          {error}
        </div>
      )}

      {loading && !stats && (
        <div
          style={{
            padding: '40px 16px',
            textAlign: 'center',
            color: 'var(--chat-text-tertiary, #9ca3af)',
            fontSize: 14,
          }}
        >
          Loading metrics...
        </div>
      )}

      {stats && (
        <>
          {/* ── Headline stat cards ─────────────────────────────── */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: 12,
              marginBottom: 24,
            }}
          >
            <StatCard
              label="Assistant messages"
              value={fmt(stats.total_messages)}
              icon={<Activity size={16} />}
              sub={`over ${stats.window_days} days`}
            />
            <StatCard
              label="Thumbs up"
              value={fmt(stats.total_thumbs_up)}
              icon={<ThumbsUp size={16} />}
            />
            <StatCard
              label="Thumbs down"
              value={fmt(stats.total_thumbs_down)}
              icon={<ThumbsDown size={16} />}
            />
            <StatCard
              label="Feedback rate"
              value={`${stats.feedback_rate_pct.toFixed(1)}%`}
              icon={<Activity size={16} />}
              sub="% of messages rated"
            />
            <StatCard
              label="Input tokens"
              value={fmt(stats.total_tokens_input)}
              icon={<Cpu size={16} />}
            />
            <StatCard
              label="Output tokens"
              value={fmt(stats.total_tokens_output)}
              icon={<Cpu size={16} />}
            />
            <StatCard
              label="Cache hit rate"
              value={`${stats.cache_hit_rate_pct.toFixed(1)}%`}
              icon={<Database size={16} />}
              sub="prompt cache reuse"
            />
          </div>

          {/* ── Daily breakdown chart ─────────────────────────────── */}
          <section
            style={{
              background: 'var(--chat-surface-1, #fff)',
              border: '1px solid var(--chat-border, #e5e7eb)',
              borderRadius: 12,
              padding: '16px 18px',
              marginBottom: 24,
            }}
          >
            <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 600 }}>
              Daily breakdown
            </h2>
            <div
              style={{
                display: 'flex',
                alignItems: 'flex-end',
                gap: 2,
                height: 120,
                overflowX: 'auto',
                paddingBottom: 4,
              }}
            >
              {stats.daily_breakdown.map((d) => {
                const h = Math.max(2, (d.messages / dailyMax) * 100);
                const ratio =
                  d.thumbs_up + d.thumbs_down > 0
                    ? d.thumbs_up / (d.thumbs_up + d.thumbs_down)
                    : 0;
                const tint =
                  d.thumbs_up + d.thumbs_down === 0
                    ? 'var(--chat-accent, #3b82f6)'
                    : ratio >= 0.6
                      ? '#10b981'
                      : ratio <= 0.3
                        ? '#ef4444'
                        : '#f59e0b';
                return (
                  <div
                    key={d.date}
                    title={`${d.date}\n${d.messages} messages\n${d.tokens.toLocaleString()} tokens\n+${d.thumbs_up} / -${d.thumbs_down}`}
                    style={{
                      width: 12,
                      minWidth: 12,
                      height: `${h}%`,
                      background: tint,
                      borderRadius: 3,
                      opacity: d.messages === 0 ? 0.2 : 1,
                    }}
                  />
                );
              })}
            </div>
            <div
              style={{
                marginTop: 8,
                fontSize: 11,
                color: 'var(--chat-text-tertiary, #9ca3af)',
                display: 'flex',
                justifyContent: 'space-between',
              }}
            >
              <span>{stats.daily_breakdown[0]?.date}</span>
              <span>
                {stats.daily_breakdown[stats.daily_breakdown.length - 1]?.date}
              </span>
            </div>
          </section>

          {/* ── Top negative prompts ─────────────────────────────── */}
          <section
            style={{
              background: 'var(--chat-surface-1, #fff)',
              border: '1px solid var(--chat-border, #e5e7eb)',
              borderRadius: 12,
              padding: '16px 18px',
            }}
          >
            <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 600 }}>
              Top thumbed-down prompts
            </h2>
            {stats.top_negative_prompts.length === 0 ? (
              <div
                style={{
                  color: 'var(--chat-text-tertiary, #9ca3af)',
                  fontSize: 13,
                  padding: '8px 0',
                }}
              >
                No negative feedback in this window.
              </div>
            ) : (
              <ol style={{ margin: 0, paddingLeft: 24 }}>
                {stats.top_negative_prompts.map((p, i) => (
                  <li
                    key={p.message_id ?? `np-${i}`}
                    style={{
                      padding: '8px 0',
                      borderBottom:
                        i === stats.top_negative_prompts.length - 1
                          ? 'none'
                          : '1px solid var(--chat-border, #f3f4f6)',
                      fontSize: 13,
                      color: 'var(--chat-text-primary, #111827)',
                      lineHeight: 1.5,
                    }}
                  >
                    <span>{p.snippet}</span>
                    <span
                      style={{
                        marginLeft: 8,
                        color: '#dc2626',
                        fontWeight: 600,
                        fontSize: 12,
                      }}
                    >
                      -{p.thumbs_down}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </div>
  );
}
