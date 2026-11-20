// Design module (ERP side of the design editor link).
/** The background-load choice (made at the design offer) and its progress; the switch to change it later. */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { megabytes, readConsent, stopBackgroundLoad, useLoadState, writeConsent, type Consent } from './data/webEditor';
import { currentPayload, startBackgroundLoad } from './editorPayload';
import { tr } from './BriefFields';

/** One line: "Loading the editor in the background: 1.2 of 5.0 MB" and the like; nothing while off. */
export function LoadHint() {
  const { t } = useTranslation();
  const s = useLoadState();
  if (s.status === 'off') return null;
  const text = s.status === 'waiting' ? tr(t, 'design.workspace.load.waiting', { total: megabytes(s.total) })
    : s.status === 'loading' ? tr(t, 'design.workspace.load.loading', { done: megabytes(s.done), total: megabytes(s.total) })
      : s.status === 'ready' ? tr(t, 'design.workspace.load.ready', { total: megabytes(s.total) })
        : tr(t, 'design.workspace.load.failed');
  return (
    <span role="status" data-testid="load-hint" className="text-xs text-content-secondary" title={s.status === 'failed' ? s.reason : undefined}>
      {text}
      {s.status === 'loading' && <progress className="ms-2 h-1.5 w-20 align-middle" max={s.total} value={s.done} />}
    </span>
  );
}

export function BackgroundLoadToggle() {
  const { t } = useTranslation();
  const [consent, setConsent] = useState<Consent>(readConsent);
  const [size, setSize] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    void currentPayload().then((p) => { if (live) setSize(p.assets.reduce((s, a) => s + a.bytes, 0)); });
    return () => { live = false; };
  }, []);
  const change = (on: boolean) => {
    writeConsent(on ? 'yes' : 'no');
    setConsent(on ? 'yes' : 'no');
    if (on) void startBackgroundLoad('yes');
    else stopBackgroundLoad();
  };
  return (
    <label className="flex items-center gap-2 text-xs text-content-secondary" data-testid="load-toggle">
      <input type="checkbox" checked={consent === 'yes'} onChange={(e) => change(e.target.checked)} />
      <span>{tr(t, 'design.workspace.load.toggle', { size: size === null ? '…' : megabytes(size) })}</span>
    </label>
  );
}
