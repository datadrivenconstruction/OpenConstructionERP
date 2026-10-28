// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useSyncExternalStore } from 'react';
import i18n from '@/app/i18n';

let version = 0;
const listeners = new Set<() => void>();
const bump = () => {
  version += 1;
  listeners.forEach((cb) => cb());
};

i18n.on('languageChanged', bump);
i18n.store?.on?.('added', bump);

const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
};

const getSnapshot = () => version;

export function useI18nReady(): number {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
