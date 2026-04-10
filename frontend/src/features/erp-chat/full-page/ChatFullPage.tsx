import { useCallback } from 'react';
import { Group, Panel, Separator } from 'react-resizable-panels';
import type { Layout } from 'react-resizable-panels';
import './chat-tokens.css';
import { useChatFullPage } from './useChatFullPage';
import ChatTopBar from './topbar/ChatTopBar';
import ChatLeftPanel from './left/ChatLeftPanel';
import DataRightPanel from './right/DataRightPanel';
import { useThemeStore } from '@/stores/useThemeStore';

const PANEL_STORAGE_KEY = 'chat-panel-sizes';

function loadSavedLayout(): Layout | undefined {
  try {
    const raw = localStorage.getItem(PANEL_STORAGE_KEY);
    if (!raw) return undefined;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Layout;
    }
    return undefined;
  } catch {
    return undefined;
  }
}

const LEFT_PANEL_ID = 'chat-left';
const RIGHT_PANEL_ID = 'chat-right';

export default function ChatFullPage() {
  const {
    messages,
    isStreaming,
    suggestions,
    dataPanelEntries,
    activePanelIndex,
    sendMessage,
    clearChat,
    setActivePanelIndex,
  } = useChatFullPage();

  // Mirror the site-wide theme so /chat respects light/dark preference.
  const resolvedTheme = useThemeStore((s) => s.resolved);

  const savedLayout = loadSavedLayout();

  const handleLayoutChanged = useCallback((layout: Layout) => {
    try {
      localStorage.setItem(PANEL_STORAGE_KEY, JSON.stringify(layout));
    } catch {
      // Ignore storage errors
    }
  }, []);

  const handleRightPanelSuggestion = useCallback(
    (text: string) => {
      sendMessage(text);
    },
    [sendMessage],
  );

  return (
    <div
      className="-mx-3 sm:-mx-4 lg:-mx-6 -mt-4 -mb-4"
      data-chat-theme={resolvedTheme}
      style={{
        height: 'calc(100vh - 56px)',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--chat-bg)',
        color: 'var(--chat-text-primary)',
        overflow: 'hidden',
      }}
    >
      <ChatTopBar onClear={clearChat} />

      <div style={{ flex: 1, overflow: 'hidden' }}>
        <Group
          orientation="horizontal"
          onLayoutChanged={handleLayoutChanged}
          defaultLayout={savedLayout}
        >
          <Panel
            id={LEFT_PANEL_ID}
            defaultSize="38%"
            minSize="28%"
            maxSize="55%"
          >
            <ChatLeftPanel
              messages={messages}
              isStreaming={isStreaming}
              suggestions={suggestions}
              onSend={sendMessage}
            />
          </Panel>

          <Separator
            style={{
              width: 4,
              background: 'var(--chat-border-subtle)',
              cursor: 'col-resize',
              transition: 'background 0.15s',
            }}
          />

          <Panel
            id={RIGHT_PANEL_ID}
            defaultSize="62%"
            minSize="40%"
          >
            <DataRightPanel
              entries={dataPanelEntries}
              activeIndex={activePanelIndex}
              onSelectIndex={setActivePanelIndex}
              onSuggestion={handleRightPanelSuggestion}
            />
          </Panel>
        </Group>
      </div>
    </div>
  );
}
