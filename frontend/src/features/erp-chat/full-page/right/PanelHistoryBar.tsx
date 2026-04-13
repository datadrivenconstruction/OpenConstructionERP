import type { DataPanelEntry } from '../../types';

interface PanelHistoryBarProps {
  entries: DataPanelEntry[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

export default function PanelHistoryBar({ entries, activeIndex, onSelect }: PanelHistoryBarProps) {
  if (entries.length <= 1) return null;

  // Show only the last 5 entries
  const visible = entries.slice(-5);
  const offset = entries.length - visible.length;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        padding: '6px 12px',
        background: 'var(--chat-surface-1)',
        borderBottom: '1px solid var(--chat-border-subtle)',
        overflowX: 'auto',
        fontFamily: 'var(--chat-font-mono)',
        fontSize: 11,
      }}
    >
      {visible.map((entry, i) => {
        const realIndex = offset + i;
        const isActive = realIndex === activeIndex;
        return (
          <button
            key={`${entry.timestamp}-${i}`}
            type="button"
            onClick={() => onSelect(realIndex)}
            style={{
              padding: '3px 8px',
              background: isActive ? 'var(--chat-surface-3)' : 'transparent',
              color: isActive ? 'var(--chat-text-primary)' : 'var(--chat-text-tertiary)',
              border: isActive ? '1px solid var(--chat-border)' : '1px solid transparent',
              borderRadius: 'var(--chat-radius-sm)',
              cursor: 'pointer',
              fontFamily: 'inherit',
              fontSize: 'inherit',
              whiteSpace: 'nowrap',
              transition: 'background 0.15s, color 0.15s',
            }}
          >
            {entry.toolName}
          </button>
        );
      })}
    </div>
  );
}
