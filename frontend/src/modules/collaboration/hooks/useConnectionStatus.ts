import { useEffect, useState, useRef, useCallback } from 'react';
import type { ProviderType } from './useYDoc';

export type ConnectionState = 'connected' | 'connecting' | 'disconnected';

export interface ConnectionStatusInfo {
  /** Current connection state */
  status: ConnectionState;
  /** Number of connected peers (excluding self) */
  peerCount: number;
  /** Timestamp of the last successful sync, or null if never synced */
  lastSyncTime: number | null;
  /** Seconds elapsed since last sync, or null if never synced */
  secondsSinceSync: number | null;
}

/**
 * Subscribe to a y-webrtc provider's connection events and
 * return reactive connection status information.
 */
export function useConnectionStatus(provider: ProviderType | null): ConnectionStatusInfo {
  const [status, setStatus] = useState<ConnectionState>('disconnected');
  const [peerCount, setPeerCount] = useState(0);
  const [lastSyncTime, setLastSyncTime] = useState<number | null>(null);
  const [secondsSinceSync, setSecondsSinceSync] = useState<number | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Compute peer count from the awareness protocol
  const updatePeerCount = useCallback((p: ProviderType) => {
    const awareness = p.awareness;
    // awareness.getStates() includes our own client, so subtract 1
    const total = awareness.getStates().size;
    setPeerCount(Math.max(0, total - 1));
  }, []);

  useEffect(() => {
    if (!provider) {
      setStatus('disconnected');
      setPeerCount(0);
      return;
    }

    // Start as "connecting" when we have a provider but haven't synced yet
    setStatus('connecting');

    const onSynced = () => {
      setStatus('connected');
      setLastSyncTime(Date.now());
      updatePeerCount(provider);
    };

    const onStatus = (event: { connected: boolean }) => {
      if (event.connected) {
        setStatus('connected');
        setLastSyncTime(Date.now());
      } else {
        setStatus('disconnected');
      }
    };

    const onPeersChange = () => {
      updatePeerCount(provider);
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const p = provider as any;
    p.on('synced', onSynced);
    p.on('status', onStatus);
    provider.awareness.on('change', onPeersChange);

    // Initial peer count read
    updatePeerCount(provider);

    return () => {
      p.off('synced', onSynced);
      p.off('status', onStatus);
      provider.awareness.off('change', onPeersChange);
    };
  }, [provider, updatePeerCount]);

  // Tick every second to update `secondsSinceSync`
  useEffect(() => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }

    if (lastSyncTime !== null) {
      const tick = () => {
        setSecondsSinceSync(Math.round((Date.now() - lastSyncTime) / 1000));
      };
      tick(); // immediate first tick
      tickRef.current = setInterval(tick, 1000);
    } else {
      setSecondsSinceSync(null);
    }

    return () => {
      if (tickRef.current) {
        clearInterval(tickRef.current);
        tickRef.current = null;
      }
    };
  }, [lastSyncTime]);

  return { status, peerCount, lastSyncTime, secondsSinceSync };
}
