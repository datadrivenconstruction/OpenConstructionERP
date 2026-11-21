// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The version check: one switch, and the sentence that says what it does.
 *
 * Asking PyPI and GitHub which release is newest is the one thing this product
 * does that nobody in the workspace started. It used to be opt-out - an
 * administrator's `OE_DISABLE_UPDATE_CHECK`, or the desktop launcher's "Turn off
 * update checks", both of which had to be found before anything stopped - so every
 * install nobody had configured asked once a day.
 *
 * It is opt-in now, and the setting rides the workspace branding record beside the
 * support destination and the Legal-link flag, for the reasons those two are there:
 * it is server-side, so it follows the workspace instead of one browser; the write
 * is admin-only and the read is public; and it needs no schema change, no migration
 * and no second cache to keep coherent.
 *
 * It sits on this tab rather than beside the support destination because this is
 * the tab that answers "what leaves this instance", which is the question the
 * setting is an answer to. The panel below it reports the posture this instance was
 * deployed with; this card holds the one part of it an administrator can change.
 *
 * The sentence under the switch is the one About renders, in both states, because
 * it comes from the same hook: two places that describe one behaviour is two places
 * to keep correct, so there is one string and two readers - the administrator
 * deciding, and the user being told.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, RefreshCw } from 'lucide-react';

import { Card } from '@/shared/ui';
import { useUpdateCheckDisclosure } from '@/shared/lib/updateCheckDisclosure';
import { useAuthStore } from '@/stores/useAuthStore';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { useToastStore } from '@/stores/useToastStore';

export function UpdateCheckCard() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  // The roles the server's admin gate lets through: superuser and owner are
  // aliases of admin there. A manager lands read-only, as the server would.
  const canEdit = userRole === 'admin' || userRole === 'superuser' || userRole === 'owner';
  const enabled = useBrandingStore((s) => s.updateCheckEnabled);
  const setEnabled = useBrandingStore((s) => s.setUpdateCheckEnabled);
  const persist = useBrandingStore((s) => s.persistToServer);
  const [busy, setBusy] = useState(false);
  const disclosure = useUpdateCheckDisclosure();

  const toggle = async (next: boolean) => {
    setBusy(true);
    setEnabled(next);
    const ok = await persist();
    setBusy(false);
    if (ok) {
      addToast({
        type: 'success',
        title: t('about.check_updates', { defaultValue: 'Check for updates' }),
        message: t('common.saved', { defaultValue: 'Saved' }),
      });
      return;
    }
    // Not admin, or no reachable server. Unlike a logo, this must not stay applied
    // locally: a browser that believes the check is on is a browser whose About
    // page tells its user something the workspace never decided.
    setEnabled(!next);
    addToast({ type: 'warning', title: t('about.check_updates', { defaultValue: 'Check for updates' }) });
  };

  return (
    <Card padding="md" data-testid="update-check-card">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <RefreshCw size={16} />
        </div>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('about.check_updates', { defaultValue: 'Check for updates' })}
          </h2>
          {/* The disclosure, and the same sentence About renders. */}
          <p className="mt-0.5 max-w-3xl text-xs text-content-secondary" data-testid="update-check-disclosure">
            {disclosure}
          </p>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-border-light px-3 py-2">
        <label className="flex cursor-pointer items-start gap-2 text-xs text-content-primary">
          <input
            type="checkbox"
            data-testid="update-check-enabled"
            className="mt-0.5 h-3.5 w-3.5 shrink-0"
            checked={enabled}
            disabled={!canEdit || busy}
            onChange={(e) => {
              void toggle(e.target.checked);
            }}
          />
          <span>
            {t('settings.update_check.label', { defaultValue: 'Ask which version is the latest' })}
          </span>
          {busy && <Loader2 size={12} className="mt-0.5 animate-spin text-content-tertiary" aria-hidden />}
        </label>
        {/* One sentence for both roles, because it is true for both: the switch is
            workspace-wide, and only an administrator can move it. A viewer reads it
            as the reason the box is greyed out; an administrator reads it as what
            they are about to do to everybody else. */}
        <p className="mt-2 text-2xs text-content-tertiary" data-testid="update-check-scope">
          {t('settings.update_check.scope', {
            defaultValue: 'Applies to every user of this workspace, and only an administrator can change it.',
          })}
        </p>
      </div>
    </Card>
  );
}

export default UpdateCheckCard;
