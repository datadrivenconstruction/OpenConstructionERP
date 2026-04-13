import type { DataPanelEntry } from '../../types';
import ToolBadge from './ToolBadge';
import PanelHistoryBar from './PanelHistoryBar';
import DataPanelRouter from './DataPanelRouter';
import DataPanelEmpty from './DataPanelEmpty';

interface DataRightPanelProps {
  entries: DataPanelEntry[];
  activeIndex: number;
  onSelectIndex: (idx: number) => void;
  onSuggestion?: (text: string) => void;
}

export default function DataRightPanel({
  entries,
  activeIndex,
  onSelectIndex,
  onSuggestion,
}: DataRightPanelProps) {
  const active = activeIndex >= 0 && activeIndex < entries.length ? entries[activeIndex] : null;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'var(--chat-bg)',
        fontFamily: 'var(--chat-font-body)',
        color: 'var(--chat-text-primary)',
      }}
    >
      {active && (
        <>
          <ToolBadge toolName={active.toolName} summary={active.summary} />
          <PanelHistoryBar entries={entries} activeIndex={activeIndex} onSelect={onSelectIndex} />
        </>
      )}

      <div style={{ flex: 1, overflow: 'hidden' }}>
        {active ? (
          <DataPanelRouter renderer={active.renderer} data={active.data} />
        ) : (
          <DataPanelEmpty onSuggestion={onSuggestion} />
        )}
      </div>
    </div>
  );
}
