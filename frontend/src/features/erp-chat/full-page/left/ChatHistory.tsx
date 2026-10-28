// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { History, Trash2, Loader2, Plus } from 'lucide-react';
import { ModuleGuideButton } from '@/shared/ui';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import type { ChatSession } from '../../types';
import { erpChatGuide } from '../../erpChatGuide';

interface ChatHistoryProps {
  sessions: ChatSession[];
  /** Sessions the caller has in total. The route serves 20 and takes no
   *  offset, so the drawer can only say how much of the history is here. */
  sessionsTotal: number;
  sessionsLoading: boolean;
  loadingSessionId: string | null;
  activeSessionId: string | null;
  onLoad: (id: string) => void;
  onDelete: (id: string) => void;
  onNew: () => void;
}

function relativeTime(iso: string, label: (k: string, d: string) => string): string {
  const ts = new Date(iso).getTime();
  if (!Number.isFinite(ts)) return '';
  const diffMin = Math.floor((Date.now() - ts) / 60000);
  if (diffMin < 1) return label('chat.history.just_now', 'just now');
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d`;
}

/**
 * Collapsible past-conversation drawer for the /chat left panel. Lists the
 * user's persisted chat sessions (backend GET /erp_chat/sessions/), lets them
 * resume one (rebuilds messages + data panel from stored renderer_data) or
 * delete it. Collapsed by default so it never crowds the conversation.
 */
export default function ChatHistory({
  sessions,
  sessionsTotal,
  sessionsLoading,
  loadingSessionId,
  activeSessionId,
  onLoad,
  onDelete,
  onNew,
}: ChatHistoryProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const label = (k: string, d: string) => t(k, { defaultValue: d });

  return (
    <div style={{ borderBottom: '1px solid var(--chat-border-subtle)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px' }}>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            flex: 1,
            background: 'none',
            border: 'none',
            color: 'var(--chat-text-secondary)',
            cursor: 'pointer',
            fontSize: 12,
            fontFamily: 'var(--chat-font-body)',
            padding: 0,
            textAlign: 'left',
          }}
        >
          <History size={14} strokeWidth={1.85} />
          {label('chat.history.title', 'Recent conversations')}
          {sessions.length > 0 && (
            <span style={{ color: 'var(--chat-text-tertiary)', fontFamily: 'var(--chat-font-mono)' }}>
              ({sessions.length})
            </span>
          )}
          <span style={{ marginLeft: 'auto', fontSize: 10, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }}>
            &#9660;
          </span>
        </button>
        <ModuleGuideButton content={erpChatGuide} />
        <button
          type="button"
          onClick={onNew}
          title={label('chat.new_chat', 'New chat')}
          aria-label={label('chat.new_chat', 'New chat')}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 24,
            height: 24,
            background: 'var(--chat-surface-2)',
            border: '1px solid var(--chat-border-subtle)',
            borderRadius: 'var(--chat-radius-sm)',
            color: 'var(--chat-text-secondary)',
            cursor: 'pointer',
            flexShrink: 0,
          }}
        >
          <Plus size={13} strokeWidth={2} />
        </button>
      </div>

      {open && (
        <div style={{ maxHeight: 220, overflowY: 'auto', padding: '0 6px 8px' }}>
          {sessionsLoading && sessions.length === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: 10, color: 'var(--chat-text-tertiary)', fontSize: 12 }}>
              <Loader2 size={13} className="animate-spin" /> {label('chat.history.loading', 'Loading…')}
            </div>
          ) : sessions.length === 0 ? (
            <div style={{ padding: 10, color: 'var(--chat-text-tertiary)', fontSize: 12, fontFamily: 'var(--chat-font-body)' }}>
              {label('chat.history.empty', 'No past conversations yet.')}
            </div>
          ) : (
            sessions.map((s) => {
              const isActive = s.id === activeSessionId;
              const isLoading = s.id === loadingSessionId;
              return (
                <div
                  key={s.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '6px 8px',
                    borderRadius: 'var(--chat-radius-sm)',
                    background: isActive ? 'var(--chat-surface-3)' : 'transparent',
                    marginBottom: 2,
                  }}
                >
                  <button
                    type="button"
                    onClick={() => onLoad(s.id)}
                    disabled={isLoading}
                    style={{
                      flex: 1,
                      minWidth: 0,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      background: 'none',
                      border: 'none',
                      color: isActive ? 'var(--chat-text-primary)' : 'var(--chat-text-secondary)',
                      cursor: isLoading ? 'wait' : 'pointer',
                      textAlign: 'left',
                      fontSize: 12,
                      fontFamily: 'var(--chat-font-body)',
                      padding: 0,
                    }}
                  >
                    {isLoading && <Loader2 size={12} className="animate-spin" style={{ flexShrink: 0 }} />}
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.title || label('chat.history.untitled', 'Untitled chat')}
                    </span>
                    <span style={{ marginLeft: 'auto', flexShrink: 0, fontSize: 10, fontFamily: 'var(--chat-font-mono)', color: 'var(--chat-text-tertiary)' }}>
                      {relativeTime(s.updated_at, label)}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(s.id)}
                    title={label('chat.history.delete', 'Delete conversation')}
                    aria-label={label('chat.history.delete', 'Delete conversation')}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: 22,
                      height: 22,
                      background: 'none',
                      border: 'none',
                      color: 'var(--chat-text-tertiary)',
                      cursor: 'pointer',
                      flexShrink: 0,
                      borderRadius: 4,
                    }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              );
            })
          )}
          {!sessionsLoading && sessions.length > 0 && (
            <div style={{ padding: '4px 8px 0' }}>
              <TruncationNotice page={{ items: sessions, total: sessionsTotal }} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
