// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One small store for personal interface preferences kept on this device.
 * `sanitize` turns whatever is stored into a valid value, so a stale or edited
 * bucket can never break a page, and the default is what "never touched" gives.
 */
import { useSyncExternalStore } from 'react';

export interface LocalPref<T> {
  read: () => T;
  write: (next: T) => void;
  /** Drop the stored choice and go back to the default. */
  reset: () => void;
  subscribe: (cb: () => void) => () => void;
  use: () => T;
  key: string;
}

export function createLocalPref<T>(key: string, sanitize: (raw: unknown) => T): LocalPref<T> {
  const listeners = new Set<() => void>();
  const fallback = sanitize(null);
  let cached: T | null = null;

  const emit = () => listeners.forEach((cb) => cb());

  const read = (): T => {
    if (cached !== null) return cached;
    try {
      cached = sanitize(JSON.parse(localStorage.getItem(key) ?? 'null'));
    } catch {
      cached = fallback;
    }
    return cached;
  };

  const persist = (value: T | null) => {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable: applies until reload */
    }
  };

  const subscribe = (cb: () => void) => {
    listeners.add(cb);
    const onStorage = (e: StorageEvent) => {
      if (e.key === key || e.key === null) {
        cached = null;
        emit();
      }
    };
    window.addEventListener('storage', onStorage);
    return () => {
      listeners.delete(cb);
      window.removeEventListener('storage', onStorage);
    };
  };

  return {
    key,
    read,
    write: (next) => {
      cached = sanitize(next);
      persist(cached);
      emit();
    },
    reset: () => {
      cached = fallback;
      persist(null);
      emit();
    },
    subscribe,
    use: () => useSyncExternalStore(subscribe, read, () => fallback),
  };
}
