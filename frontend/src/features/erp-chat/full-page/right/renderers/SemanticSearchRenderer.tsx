// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { unwrapList } from './normalize';
import { fmtFixed } from '@/shared/lib/formatters';

/**
 * Renders the `semantic_search` tool result, shared by every `search_*`
 * tool (search_boq_positions, search_documents, search_risks, search_rfis,
 * search_submittals, search_correspondence, search_bim_elements,
 * search_tasks, search_anything). The backend payload is
 * `{ query, type, hits: [...], total, facets }` where each hit carries
 * `{ id, title, snippet, score, module, collection, project_id, payload }`.
 *
 * Hits are grouped by module so a cross-collection `search_anything` reads
 * cleanly, and each hit shows its relevance score as a confidence bar - the
 * platform's "AI suggests, human confirms" posture made visible.
 */
interface Hit {
  id?: string;
  title?: string;
  snippet?: string;
  score?: number;
  module?: string;
  collection?: string;
  project_id?: string;
}

const MODULE_LABELS: Record<string, string> = {
  boq: 'BOQ',
  documents: 'Documents',
  tasks: 'Tasks',
  risks: 'Risks',
  bim: 'BIM',
  rfi: 'RFIs',
  submittals: 'Submittals',
  correspondence: 'Correspondence',
  chat: 'Chat',
};

function scoreColor(score: number): string {
  if (score >= 0.7) return 'var(--chat-tool-done)';
  if (score >= 0.4) return '#f0883e';
  return 'var(--chat-text-tertiary)';
}

function HitCard({ hit }: { hit: Hit }) {
  const score = typeof hit.score === 'number' ? hit.score : 0;
  // Cosine scores can exceed 1 with some rerankers; clamp for the bar width.
  const pct = Math.max(0, Math.min(100, Math.round(score * 100)));
  return (
    <div
      style={{
        background: 'var(--chat-surface-1)',
        border: '1px solid var(--chat-border-subtle)',
        borderRadius: 'var(--chat-radius-sm)',
        padding: '10px 12px',
        marginBottom: 6,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--chat-text-primary)', flex: 1 }}>
          {hit.title ?? '(untitled)'}
        </span>
        <span
          style={{
            fontFamily: 'var(--chat-font-mono)',
            fontSize: 11,
            color: scoreColor(score),
            whiteSpace: 'nowrap',
          }}
        >
          {fmtFixed(score, 2)}
        </span>
      </div>
      {hit.snippet && (
        <div style={{ fontSize: 12, color: 'var(--chat-text-secondary)', marginTop: 4, lineHeight: 1.5 }}>
          {hit.snippet}
        </div>
      )}
      <div
        style={{
          marginTop: 8,
          height: 3,
          borderRadius: 2,
          background: 'var(--chat-surface-3)',
          overflow: 'hidden',
        }}
      >
        <div style={{ width: `${pct}%`, height: '100%', background: scoreColor(score) }} />
      </div>
    </div>
  );
}

export default function SemanticSearchRenderer({ data }: { data: unknown }) {
  const { t } = useTranslation();
  const hits = unwrapList(data, ['hits']) as Hit[];
  const obj = (data && typeof data === 'object' ? data : {}) as { query?: string; total?: number };

  if (hits.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--chat-text-tertiary)', textAlign: 'center', fontFamily: 'var(--chat-font-body)' }}>
        {obj.query ? `No semantic matches for "${obj.query}"` : 'No semantic matches'}
      </div>
    );
  }

  // Group by module so a fan-out search_anything is legible.
  const groups = new Map<string, Hit[]>();
  for (const h of hits) {
    const key = h.module ?? h.collection ?? 'other';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(h);
  }

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 12, fontFamily: 'var(--chat-font-body)' }}>
      {obj.query && (
        <div style={{ fontSize: 12, color: 'var(--chat-text-tertiary)', marginBottom: 10 }}>
          {/* The count is its own counted phrase so i18next can pick the
              form the reader's language needs; the query follows it as a
              quoted label rather than inside an English "for" clause. */}
          {t('erp_chat.search.matches_count', {
            count: hits.length,
            defaultValue_one: '{{count}} match',
            defaultValue_other: '{{count}} matches',
          })}
          {': '}
          <span style={{ color: 'var(--chat-text-primary)' }}>&ldquo;{obj.query}&rdquo;</span>
        </div>
      )}
      {[...groups.entries()].map(([module, items]) => (
        <div key={module} style={{ marginBottom: 14 }}>
          {groups.size > 1 && (
            <div
              style={{
                fontSize: 11,
                fontFamily: 'var(--chat-font-mono)',
                color: 'var(--chat-text-secondary)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: 6,
              }}
            >
              {MODULE_LABELS[module] ?? module} · {items.length}
            </div>
          )}
          {items.map((h, i) => (
            <HitCard key={h.id ?? `${module}-${i}`} hit={h} />
          ))}
        </div>
      ))}
    </div>
  );
}
