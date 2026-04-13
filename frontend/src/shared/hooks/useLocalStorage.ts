import { useState, useCallback } from 'react';

/**
 * Hook that persists state to localStorage with automatic JSON
 * serialization.  Falls back to `defaultValue` on parse errors or
 * when running in environments without localStorage (SSR, incognito).
 */
export function useLocalStorage<T>(
  key: string,
  defaultValue: T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [storedValue, setStoredValue] = useState<T>(() => {
    try {
      const item = localStorage.getItem(key);
      return item !== null ? (JSON.parse(item) as T) : defaultValue;
    } catch {
      return defaultValue;
    }
  });

  const setValue = useCallback(
    (value: T | ((prev: T) => T)) => {
      setStoredValue((prev) => {
        const next = value instanceof Function ? value(prev) : value;
        try {
          localStorage.setItem(key, JSON.stringify(next));
        } catch {
          // Storage full or unavailable — state still updates in memory
        }
        return next;
      });
    },
    [key],
  );

  return [storedValue, setValue];
}
