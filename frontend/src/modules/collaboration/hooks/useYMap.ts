import { useEffect, useState, useCallback } from 'react';
import * as Y from 'yjs';

/**
 * Subscribe to a Y.Map and return its contents as a reactive Record.
 * Changes from remote peers trigger re-renders.
 */
export function useYMap<T extends Record<string, unknown>>(
  doc: Y.Doc | null,
  mapName: string,
): {
  data: Record<string, T>;
  set: (key: string, value: T) => void;
  del: (key: string) => void;
} {
  const [data, setData] = useState<Record<string, T>>({});

  useEffect(() => {
    if (!doc) return;

    const ymap = doc.getMap<T>(mapName);

    const syncState = () => {
      const obj: Record<string, T> = {};
      ymap.forEach((val, key) => {
        obj[key] = val;
      });
      setData(obj);
    };

    // Initial sync
    syncState();

    // Listen for remote changes
    const observer = () => syncState();
    ymap.observeDeep(observer);

    return () => {
      ymap.unobserveDeep(observer);
    };
  }, [doc, mapName]);

  const set = useCallback(
    (key: string, value: T) => {
      if (!doc) return;
      const ymap = doc.getMap<T>(mapName);
      ymap.set(key, value);
    },
    [doc, mapName],
  );

  const del = useCallback(
    (key: string) => {
      if (!doc) return;
      const ymap = doc.getMap<T>(mapName);
      ymap.delete(key);
    },
    [doc, mapName],
  );

  return { data, set, del };
}
