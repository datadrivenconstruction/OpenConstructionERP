// Design module (ERP side of the design editor link).
/**
 * The two offer points of the design editor link, one component: the question in the first-run set-up
 * ("Do you work with models and drawings?") and the line in the empty states of the geometry sections.
 * It shows only while the module is switched off; saying yes switches it on and nothing else changes.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PencilRuler } from 'lucide-react';
import { useModuleStore } from '@/stores/useModuleStore';
import { DISMISS_KEY, MODULE_KEY, shouldOffer, type OfferVariant } from './data/offer';
import { tr } from './BriefFields';
import { writeConsent } from './data/webEditor';
import { startBackgroundLoad } from './editorPayload';
import { LoadHint } from './BackgroundLoad';

const readDismissed = (): boolean => {
  try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch { return false; }
};

export function DesignOffer({ variant }: { variant: OfferVariant }) {
  const { t } = useTranslation();
  // Only an explicit `true` counts as on: the store reports unknown modules as on by default.
  const enabled = useModuleStore((s) => s.enabledModules[MODULE_KEY] === true);
  const setEnabled = useModuleStore((s) => s.setModuleEnabled);
  const [dismissed, setDismissed] = useState(readDismissed);
  const [justEnabled, setJustEnabled] = useState(false);
  const [justDeclined, setJustDeclined] = useState(false);

  if (justEnabled) {
    return (
      <div role="status" data-testid="design-offer-done" className="flex flex-col gap-1 text-sm">
        <p>{tr(t, 'design.offer.enabled')} <Link className="text-oe-blue-text underline" to="/design/editor">{tr(t, 'design.offer.go')}</Link></p>
        <LoadHint />
      </div>
    );
  }
  // "Not now" is not a dead end: say where it can be switched on later, for as long as this screen stays.
  if (justDeclined) {
    return (
      <p role="status" data-testid="design-offer-later" className="my-4 text-sm text-content-secondary">
        {tr(t, 'design.offer.later_hint')} <Link className="text-oe-blue-text underline" to="/modules">{tr(t, 'design.offer.later_go')}</Link>
      </p>
    );
  }
  if (!shouldOffer(variant, enabled, dismissed)) return null;

  const yes = () => {
    setEnabled(MODULE_KEY, true);
    // yes = the editor may be fetched in idle time; changed later on the editor page
    writeConsent('yes');
    void startBackgroundLoad('yes');
    setJustEnabled(true);
  };
  const no = () => {
    try { localStorage.setItem(DISMISS_KEY, '1'); } catch { /* shows again next time */ }
    writeConsent('no');
    setDismissed(true);
    setJustDeclined(true);
  };

  if (variant === 'empty' || variant === 'drawings') {
    return (
      <div data-testid={variant === 'drawings' ? 'design-offer-drawings' : 'design-offer-empty'} className="mt-2 flex flex-wrap items-center gap-2 text-sm text-content-secondary">
        <PencilRuler size={14} aria-hidden />
        <span>{tr(t, variant === 'drawings' ? 'design.offer.drawings' : 'design.offer.empty')}</span>
        <button type="button" className="text-oe-blue-text underline" onClick={yes}>{tr(t, 'design.offer.enable')}</button>
      </div>
    );
  }
  return (
    <section data-testid="design-offer-tour" aria-labelledby="design-offer-q" className="my-4 w-full max-w-md rounded-lg border border-border-light bg-surface-secondary p-4 text-start">
      <h3 id="design-offer-q" className="flex items-center gap-2 text-sm font-medium">
        <PencilRuler size={16} aria-hidden />
        {tr(t, 'design.offer.question')}
      </h3>
      <p className="mt-1 text-sm text-content-secondary">{tr(t, 'design.offer.explain')}</p>
      <div className="mt-3 flex gap-2">
        <button type="button" className="rounded bg-oe-blue px-3 py-1.5 text-sm text-white" onClick={yes}>{tr(t, 'design.offer.yes')}</button>
        <button type="button" className="rounded border border-border-light px-3 py-1.5 text-sm" onClick={no}>{tr(t, 'design.offer.later')}</button>
      </div>
    </section>
  );
}
