import { useEffect, useState, useCallback, useMemo } from 'react';
import type { ProviderType } from './useYDoc';
import type { AwarenessState, CollabUser, CursorPosition } from '../types';
import { pickColor } from '../types';

/**
 * Track local + remote user presence via Yjs awareness protocol.
 * Works with both WebRTC and WebSocket providers.
 */
export function useAwareness(
  provider: ProviderType | null,
  localUser: { userId: string; userName: string },
): {
  users: CollabUser[];
  setCursor: (cursor: CursorPosition | null) => void;
} {
  const [remoteStates, setRemoteStates] = useState<Map<number, AwarenessState>>(new Map());
  const [localClientId, setLocalClientId] = useState<number | null>(null);

  // Set local awareness state
  useEffect(() => {
    if (!provider) return;

    const awareness = provider.awareness;
    setLocalClientId(awareness.clientID);

    // Pick a color based on clientID
    const color = pickColor(awareness.clientID);

    awareness.setLocalState({
      userId: localUser.userId,
      userName: localUser.userName,
      color,
      cursor: null,
      lastActive: Date.now(),
    } satisfies AwarenessState);

    const onChange = () => {
      const states = new Map<number, AwarenessState>();
      awareness.getStates().forEach((state, clientId) => {
        if (state && typeof state === 'object' && 'userId' in state) {
          states.set(clientId, state as AwarenessState);
        }
      });
      setRemoteStates(new Map(states));
    };

    awareness.on('change', onChange);
    // Trigger initial read
    onChange();

    return () => {
      awareness.off('change', onChange);
    };
  }, [provider, localUser.userId, localUser.userName]);

  // Build user list
  const users: CollabUser[] = useMemo(() => {
    const result: CollabUser[] = [];
    remoteStates.forEach((state, clientId) => {
      result.push({
        userId: state.userId,
        userName: state.userName,
        color: state.color,
        cursor: state.cursor,
        isLocal: clientId === localClientId,
      });
    });
    return result;
  }, [remoteStates, localClientId]);

  // Update local cursor position
  const setCursor = useCallback(
    (cursor: CursorPosition | null) => {
      if (!provider) return;
      const awareness = provider.awareness;
      const current = awareness.getLocalState() as AwarenessState | null;
      if (current) {
        awareness.setLocalState({
          ...current,
          cursor,
          lastActive: Date.now(),
        });
      }
    },
    [provider],
  );

  return { users, setCursor };
}
