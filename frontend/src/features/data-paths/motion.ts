// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState } from 'react';

function query(q: string): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.(q).matches;
}

/** Live `prefers-reduced-motion: reduce`; every animation in the data path views checks it. */
export function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(() => query('(prefers-reduced-motion: reduce)'));
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!mq) return undefined;
    const on = () => setReduce(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return reduce;
}

/** True under 640 px: the list is the default there and columns stack. */
export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => query('(max-width: 639px)'));
  useEffect(() => {
    const mq = window.matchMedia?.('(max-width: 639px)');
    if (!mq) return undefined;
    const on = () => setNarrow(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return narrow;
}
