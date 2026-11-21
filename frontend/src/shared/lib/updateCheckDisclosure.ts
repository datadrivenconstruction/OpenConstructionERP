// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The one sentence that says what this installation does about versions.
 *
 * Two places have to tell the truth about the same behaviour: Settings, where an
 * administrator decides it, and About, where every user is told it. Written twice
 * they drift - one gets reworded, the other keeps describing what the product used
 * to do - and a privacy sentence that has drifted is worse than one that is
 * missing, because it is still being read as accurate.
 *
 * So there is one hook and two readers. It answers from the workspace branding
 * record, which is the setting itself: server-side, admin-only to write, public to
 * read, and false until an administrator turns it on.
 *
 * Two things this sentence deliberately does not claim.
 *
 * It does not say whether an operator has since overruled the setting from outside
 * the product - `OE_DISABLE_UPDATE_CHECK` in the server's environment, or the
 * desktop launcher's `~/.openestimate/no-update-check`. Both still win, and the
 * backend reads both on every call, so a check the workspace asked for can still
 * come back `check_disabled`; the notice that asked says so, from that answer.
 *
 * And it does not cover the one other place this product asks about versions: the
 * DDC converter banner on the BIM and Projects pages compares each *installed
 * converter* against GitHub through `/api/system/converters/version-check`. That is
 * a converter feature with its own endpoint and its own six-hour server cache, not
 * a self-check, and this setting does not govern it - which is why the sentence
 * names the product instead of saying nothing is ever checked.
 */
import { useTranslation } from 'react-i18next';
import { useBrandingStore } from '@/stores/useBrandingStore';

/** What the product does about versions, in the reader's language, in one sentence. */
export function useUpdateCheckDisclosure(): string {
  const { t } = useTranslation();
  const enabled = useBrandingStore((s) => s.updateCheckEnabled);
  return enabled
    ? t('about.check_updates_hint', {
        defaultValue: 'Asks PyPI and GitHub which version is the latest. Nothing about you is sent.',
      })
    : t('about.update_check_off', {
        defaultValue: 'This installation does not check the internet for a newer version of the product.',
      });
}
