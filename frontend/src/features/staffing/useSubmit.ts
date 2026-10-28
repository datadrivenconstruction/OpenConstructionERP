// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One form submission: busy while it runs, and when the server refuses, the
// refusal stays in the dialog in the server's own words instead of closing it.

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { refusalText, type TFn } from './labels';

export function useSubmit(onDone: () => void) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (err) {
      setError(refusalText(t as TFn, err));
    } finally {
      setBusy(false);
    }
  };
  const reset = useCallback(() => setError(null), []);
  return { busy, error, setError, run, reset };
}
