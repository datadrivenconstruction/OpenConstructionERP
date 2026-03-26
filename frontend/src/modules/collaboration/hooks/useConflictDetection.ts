import { useEffect, useState, useCallback, useRef } from 'react';
import * as Y from 'yjs';

/**
 * Represents a single merge conflict between a local pending change and
 * an incoming remote change on the same Y.Map key.
 */
export interface ConflictItem {
  /** Unique conflict identifier */
  id: string;
  /** The field / key that was concurrently changed */
  field: string;
  /** Human-readable ordinal of the BOQ position, e.g. "01.02.003" */
  positionOrdinal: string;
  /** Stringified representation of the locally-held value */
  localValue: string;
  /** Stringified representation of the incoming remote value */
  remoteValue: string;
  /** Display name of the remote user who made the change */
  remoteUser: string;
  /** When the conflict was detected */
  timestamp: Date;
}

/**
 * Resolution choices available to the user.
 * - `keep_mine`   – discard remote change, keep local value
 * - `accept_theirs` – overwrite local value with remote value
 * - `manual`      – user has provided a custom merged value (passed separately)
 */
export type ConflictResolution = 'keep_mine' | 'accept_theirs' | 'manual';

interface PendingLocalChange {
  field: string;
  positionOrdinal: string;
  value: string;
  capturedAt: number;
}

/**
 * Monitor a Y.Map for situations where a remote update arrives while the user
 * has an unconfirmed local change for the same key.  When that happens, a
 * ConflictItem is emitted so the UI can ask the user how to resolve it.
 *
 * Usage
 * -----
 * ```tsx
 * const { conflicts, resolveConflict, dismissConflict } = useConflictDetection(doc, 'positions');
 * ```
 *
 * The hook deliberately does NOT apply resolutions to the Y.Doc — that is the
 * caller's responsibility (e.g. write the merged value back via useYMap).
 */
export function useConflictDetection(
  doc: Y.Doc | null,
  mapName: string,
): {
  conflicts: ConflictItem[];
  resolveConflict: (id: string, resolution: ConflictResolution, manualValue?: string) => void;
  dismissConflict: (id: string) => void;
} {
  const [conflicts, setConflicts] = useState<ConflictItem[]>([]);

  // keyed by `${positionOrdinal}::${field}` → pending local change info
  const pendingRef = useRef<Map<string, PendingLocalChange>>(new Map());
  // track which conflict IDs have already been resolved / dismissed
  const resolvedRef = useRef<Set<string>>(new Set());
  // snapshot of the last known remote values so we can diff on changes
  const remoteSnapshotRef = useRef<Map<string, string>>(new Map());

  // -------------------------------------------------------------------
  // Internal helpers
  // -------------------------------------------------------------------

  const makeKey = (ordinal: string, field: string) => `${ordinal}::${field}`;

  const stringify = (value: unknown): string => {
    if (value === null || value === undefined) return '';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  };

  const addConflict = useCallback((item: ConflictItem) => {
    setConflicts((prev) => {
      // Deduplicate: one active conflict per (positionOrdinal, field)
      const filtered = prev.filter(
        (c) => !(c.positionOrdinal === item.positionOrdinal && c.field === item.field),
      );
      return [...filtered, item];
    });
  }, []);

  // -------------------------------------------------------------------
  // Observe Y.Map for remote changes
  // -------------------------------------------------------------------

  useEffect(() => {
    if (!doc) return;

    const ymap = doc.getMap(mapName);

    const observer = (events: Y.YEvent<Y.AbstractType<unknown>>[], transaction: Y.Transaction) => {
      // Only react to changes that originate from a remote peer
      if (transaction.local) return;

      for (const event of events) {
        if (!(event instanceof Y.YMapEvent)) continue;

        event.keysChanged.forEach((key) => {
          const rawValue = ymap.get(key);

          // The key format we use in Y.Map is `${ordinal}::${field}`.
          // If the key does not contain "::", skip — it is not a position field.
          if (!key.includes('::')) return;

          const colonIdx = key.indexOf('::');
          const positionOrdinal = key.slice(0, colonIdx);
          const field = key.slice(colonIdx + 2);
          const remoteValue = stringify(rawValue);
          const pendingKey = makeKey(positionOrdinal, field);
          const pendingChange = pendingRef.current.get(pendingKey);

          // Update remote snapshot
          remoteSnapshotRef.current.set(key, remoteValue);

          if (!pendingChange) return;

          // If values are identical after remote update, no conflict
          if (pendingChange.value === remoteValue) {
            pendingRef.current.delete(pendingKey);
            return;
          }

          // Determine who made the remote change via awareness (best effort)
          let remoteUser = 'Unknown user';
          try {
            const doc2 = doc as Y.Doc & { awareness?: { getStates: () => Map<number, Record<string, unknown>> } };
            if (doc2.awareness) {
              doc2.awareness.getStates().forEach((state) => {
                if (state && typeof state === 'object' && 'userName' in state) {
                  remoteUser = String((state as { userName: string }).userName);
                }
              });
            }
          } catch {
            // awareness not available — use fallback
          }

          const conflictId = `${pendingKey}__${Date.now()}`;

          if (resolvedRef.current.has(conflictId)) return;

          addConflict({
            id: conflictId,
            field,
            positionOrdinal,
            localValue: pendingChange.value,
            remoteValue,
            remoteUser,
            timestamp: new Date(),
          });
        });
      }
    };

    ymap.observeDeep(observer);
    return () => {
      ymap.unobserveDeep(observer);
    };
  }, [doc, mapName, addConflict]);

  // -------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------

  /**
   * Register a local pending change so the hook can detect conflicts if a
   * competing remote update arrives before the local change is confirmed.
   *
   * Call this immediately before (or after) writing to the Y.Map locally.
   */
  const trackLocalChange = useCallback(
    (positionOrdinal: string, field: string, value: string) => {
      const key = makeKey(positionOrdinal, field);
      pendingRef.current.set(key, {
        field,
        positionOrdinal,
        value,
        capturedAt: Date.now(),
      });
    },
    [],
  );

  /**
   * Mark a conflict as resolved.  The resolution strategy determines what
   * should happen to the underlying Y.Map — that part is left to the caller.
   */
  const resolveConflict = useCallback(
    (id: string, _resolution: ConflictResolution, _manualValue?: string) => {
      resolvedRef.current.add(id);
      setConflicts((prev) => prev.filter((c) => c.id !== id));
    },
    [],
  );

  /**
   * Dismiss a conflict without any explicit resolution (e.g. "cancel" / ignore).
   */
  const dismissConflict = useCallback((id: string) => {
    setConflicts((prev) => prev.filter((c) => c.id !== id));
  }, []);

  return { conflicts, resolveConflict, dismissConflict, trackLocalChange } as {
    conflicts: ConflictItem[];
    resolveConflict: (id: string, resolution: ConflictResolution, manualValue?: string) => void;
    dismissConflict: (id: string) => void;
    /** Exposed for testing and advanced usage; not part of the main API contract */
    trackLocalChange: (positionOrdinal: string, field: string, value: string) => void;
  };
}
