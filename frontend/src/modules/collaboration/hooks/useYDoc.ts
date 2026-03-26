import { useEffect, useRef, useState } from 'react';
import * as Y from 'yjs';
import { WebrtcProvider } from 'y-webrtc';
import { WebsocketProvider } from 'y-websocket';

export type ProviderType = WebrtcProvider | WebsocketProvider;

export interface UseYDocResult {
  doc: Y.Doc | null;
  provider: ProviderType | null;
  connected: boolean;
  /** Which provider type is currently active */
  providerKind: 'webrtc' | 'websocket' | null;
}

/**
 * Default WebSocket URL for the y-websocket fallback.
 * Can be overridden via localStorage for testing/production.
 */
const WS_URL_KEY = 'oe_collab_ws_url';
const DEFAULT_WS_URL = 'wss://demos.yjs.dev/ws';

function getWsUrl(): string {
  try {
    return localStorage.getItem(WS_URL_KEY) || DEFAULT_WS_URL;
  } catch {
    return DEFAULT_WS_URL;
  }
}

/**
 * Initialize a Yjs document with WebRTC provider.
 * Falls back to WebSocket if WebRTC fails to connect within 8 seconds.
 * Room name = `boq:{boqId}`.
 */
export function useYDoc(boqId: string | undefined): UseYDocResult {
  const [connected, setConnected] = useState(false);
  const [providerKind, setProviderKind] = useState<'webrtc' | 'websocket' | null>(null);
  const docRef = useRef<Y.Doc | null>(null);
  const providerRef = useRef<ProviderType | null>(null);

  useEffect(() => {
    if (!boqId) return;

    const doc = new Y.Doc();
    const roomName = `boq:${boqId}`;
    let fallbackTimer: ReturnType<typeof setTimeout> | undefined;
    let wsProvider: WebsocketProvider | null = null;

    // Start with WebRTC
    const rtcProvider = new WebrtcProvider(roomName, doc, {
      signaling: ['wss://signaling.yjs.dev', 'wss://y-webrtc-signaling-eu.herokuapp.com'],
    });

    const onRtcSynced = () => {
      setConnected(true);
      setProviderKind('webrtc');
      if (fallbackTimer) clearTimeout(fallbackTimer);
    };

    rtcProvider.on('synced', onRtcSynced);
    rtcProvider.on('status', (event: { connected: boolean }) => {
      if (event.connected) {
        setConnected(true);
        setProviderKind('webrtc');
        if (fallbackTimer) clearTimeout(fallbackTimer);
      }
    });

    docRef.current = doc;
    providerRef.current = rtcProvider;
    setProviderKind('webrtc');

    // Fallback: if WebRTC doesn't connect within 8s, add WebSocket provider
    fallbackTimer = setTimeout(() => {
      if (connected) return; // Already connected via WebRTC
      try {
        wsProvider = new WebsocketProvider(getWsUrl(), roomName, doc);
        wsProvider.on('status', (event: { status: string }) => {
          if (event.status === 'connected') {
            setConnected(true);
            setProviderKind('websocket');
            providerRef.current = wsProvider;
          }
        });
      } catch {
        // WebSocket fallback failed — stay with WebRTC attempt
      }
    }, 8000);

    return () => {
      if (fallbackTimer) clearTimeout(fallbackTimer);
      rtcProvider.disconnect();
      rtcProvider.destroy();
      if (wsProvider) {
        wsProvider.disconnect();
        wsProvider.destroy();
      }
      doc.destroy();
      docRef.current = null;
      providerRef.current = null;
      setConnected(false);
      setProviderKind(null);
    };
  }, [boqId]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    doc: docRef.current,
    provider: providerRef.current,
    connected,
    providerKind,
  };
}
