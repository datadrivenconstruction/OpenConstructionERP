// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useCallback, useEffect, useRef } from 'react';
import { Group, Panel, Separator } from 'react-resizable-panels';
import type { GroupImperativeHandle, Layout, LayoutChangedMeta } from 'react-resizable-panels';
import './chat-tokens.css';
import { useChatFullPage } from './useChatFullPage';
import ChatLeftPanel from './left/ChatLeftPanel';
import DataRightPanel from './right/DataRightPanel';
import AIConfigBanner from './AIConfigBanner';
import { AiDisclosure } from '../AiDisclosure';
import { useIsMobileViewport } from '../useFloatingChat';
import { useThemeStore } from '@/stores/useThemeStore';

const PANEL_STORAGE_KEY = 'chat-panel-sizes';
const LEFT_PANEL_ID = 'chat-left';
const RIGHT_PANEL_ID = 'chat-right';

function loadSavedLayout(): Layout | undefined {
  try {
    const raw = localStorage.getItem(PANEL_STORAGE_KEY);
    if (!raw) return undefined;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return undefined;
    if (Object.keys(parsed).length !== 2) return undefined;
    const left: unknown = parsed[LEFT_PANEL_ID];
    const right: unknown = parsed[RIGHT_PANEL_ID];
    if (typeof left !== 'number' || typeof right !== 'number') return undefined;
    if (!Number.isFinite(left) || !Number.isFinite(right) || left <= 0 || right <= 0) return undefined;
    if (Math.abs(left + right - 100) > 0.01) return undefined;
    return { [LEFT_PANEL_ID]: left, [RIGHT_PANEL_ID]: right };
  } catch {
    return undefined;
  }
}

export default function ChatFullPage() {
  const mobile = useIsMobileViewport(768);
  const groupRef = useRef<GroupImperativeHandle>(null);
  useEffect(() => {
    groupRef.current?.setLayout(mobile
      ? { [LEFT_PANEL_ID]: 60, [RIGHT_PANEL_ID]: 40 }
      : loadSavedLayout() ?? { [LEFT_PANEL_ID]: 38, [RIGHT_PANEL_ID]: 62 });
  }, [mobile]);
  const {
    messages,
    isStreaming,
    sessionId,
    suggestions,
    dataPanelEntries,
    activePanelIndex,
    aiConfigured,
    sessions,
    sessionsTotal,
    sessionsLoading,
    loadingSessionId,
    sendMessage,
    clearChat,
    setActivePanelIndex,
    loadSession,
    removeSession,
  } = useChatFullPage();

  // Mirror the site-wide theme so /chat respects light/dark preference.
  const resolvedTheme = useThemeStore((s) => s.resolved);

  const savedLayout = loadSavedLayout();

  const handleLayoutChanged = useCallback((layout: Layout, meta: LayoutChangedMeta) => {
    if (!meta.isUserInteraction) return;
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
      className="-mx-4 sm:-mx-7 -mt-6 -mb-6 min-w-0 border-l border-border-light"
      data-chat-theme={resolvedTheme}
      style={{
        height: 'calc(100dvh - 56px)',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--chat-bg)',
        color: 'var(--chat-text-primary)',
        overflow: 'hidden',
      }}
    >
      {/* The redundant chat-specific top bar ("ERP AI Assistant" + back +
          clear) was removed in v1.3.29 — the app's main layout already
          provides a header, so the chat bar duplicated UI and didn't
          match the rest of the site. Clear chat now lives in the input
          bar (left panel). */}
      {/* The route header and old ChatTopBar are not the chat's persistent
          identity. Keep disclosure visible independently of setup or history. */}
      <AiDisclosure />
      <AIConfigBanner />

      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <Group
          groupRef={groupRef}
          orientation={mobile ? 'vertical' : 'horizontal'}
          onLayoutChanged={mobile ? undefined : handleLayoutChanged}
          defaultLayout={mobile ? undefined : savedLayout}
        >
          <Panel
            id={LEFT_PANEL_ID}
            defaultSize={mobile ? '60%' : '38%'}
            minSize={mobile ? '40%' : '28%'}
            maxSize={mobile ? '80%' : '55%'}
          >
            <ChatLeftPanel
              messages={messages}
              isStreaming={isStreaming}
              suggestions={suggestions}
              onSend={sendMessage}
              onClear={clearChat}
              aiConfigured={aiConfigured}
              sessions={sessions}
              sessionsTotal={sessionsTotal}
              sessionsLoading={sessionsLoading}
              loadingSessionId={loadingSessionId}
              activeSessionId={sessionId}
              onLoadSession={(id) => void loadSession(id)}
              onDeleteSession={(id) => void removeSession(id)}
            />
          </Panel>

          <Separator
            style={{
              width: mobile ? '100%' : 4,
              height: mobile ? 4 : undefined,
              background: 'var(--chat-border)',
              cursor: mobile ? 'row-resize' : 'col-resize',
              transition: 'background 0.15s',
            }}
          />

          <Panel
            id={RIGHT_PANEL_ID}
            defaultSize={mobile ? '40%' : '62%'}
            minSize={mobile ? '20%' : '40%'}
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
