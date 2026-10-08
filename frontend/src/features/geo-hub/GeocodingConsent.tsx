// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The one-time question: may project addresses go to a geocoder?
 *
 * A site address is often someone's home, so the server sends nothing until
 * a manager answers. ``GeocodingConsentPrompt`` sits above every address
 * field and shows only while the question is open; ``GeocodingConsentPanel``
 * lets an operator change the answer later on the Geo Hub admin page.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MapPin } from 'lucide-react';

import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import { getGeocodingConsent, setGeocodingConsent, type GeocodingConsent } from './api';

const QUERY_KEY = ['geo-hub', 'geocoding-consent'];

type Choice = 'allow' | 'deny' | 'mirror';

function useConsent() {
  return useQuery({ queryKey: QUERY_KEY, queryFn: getGeocodingConsent, staleTime: 60_000 });
}

function ChoiceForm({ current, onDone }: { current?: GeocodingConsent; onDone?: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [mirrorOpen, setMirrorOpen] = useState(current?.state === 'mirror');
  const [mirrorUrl, setMirrorUrl] = useState(current?.mirror_url ?? '');

  const save = useMutation({
    mutationFn: (choice: Choice) =>
      setGeocodingConsent({ choice, mirror_url: choice === 'mirror' ? mirrorUrl.trim() : null }),
    onSuccess: (data) => {
      qc.setQueryData(QUERY_KEY, data);
      addToast({
        type: 'success',
        title: t('geo_hub.consent.saved', { defaultValue: 'Your answer is saved' }),
      });
      onDone?.();
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('geo_hub.consent.save_failed', { defaultValue: 'Could not save the answer' }), message: err.message });
    },
  });

  const mirrorValid = /^https?:\/\/\S+$/i.test(mirrorUrl.trim());

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="primary" disabled={save.isPending} onClick={() => save.mutate('allow')}>
          {t('geo_hub.consent.allow', { defaultValue: 'Send to OpenStreetMap' })}
        </Button>
        <Button size="sm" variant="secondary" disabled={save.isPending} onClick={() => save.mutate('deny')}>
          {t('geo_hub.consent.deny', { defaultValue: 'Do not send' })}
        </Button>
        <Button size="sm" variant="ghost" disabled={save.isPending} onClick={() => setMirrorOpen((v) => !v)}>
          {t('geo_hub.consent.mirror', { defaultValue: 'Use our own server' })}
        </Button>
      </div>
      {mirrorOpen && (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="geo-consent-mirror" className="sr-only">
            {t('geo_hub.consent.mirror_label', { defaultValue: 'Address of your Nominatim server' })}
          </label>
          <input
            id="geo-consent-mirror"
            type="url"
            value={mirrorUrl}
            onChange={(e) => setMirrorUrl(e.target.value)}
            placeholder="https://nominatim.example.com"
            className="min-w-0 flex-1 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
          />
          <Button
            size="sm"
            variant="primary"
            disabled={!mirrorValid || save.isPending}
            onClick={() => save.mutate('mirror')}
          >
            {t('geo_hub.consent.mirror_save', { defaultValue: 'Use this server' })}
          </Button>
        </div>
      )}
    </div>
  );
}

function Explanation() {
  const { t } = useTranslation();
  return (
    <p className="text-xs text-content-secondary">
      {t('geo_hub.consent.explain', {
        defaultValue:
          'To place a project on the map from its address, the address is sent to the public OpenStreetMap services (Nominatim, and Photon for suggestions while typing). A site address is often a private home, so nothing is sent until you decide. You can change this later on the Geo Hub admin page.',
      })}
    </p>
  );
}

/** Shown above an address field while the installation has not answered. */
export function GeocodingConsentPrompt() {
  const { t } = useTranslation();
  const { data } = useConsent();
  if (!data || data.state !== 'unanswered') return null;
  return (
    <div className="mb-2 space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-900/20">
      <div className="flex items-center gap-2 text-sm font-medium text-content-primary">
        <MapPin size={14} aria-hidden />
        {t('geo_hub.consent.title', { defaultValue: 'May addresses be sent to a map service?' })}
      </div>
      {data.can_decide ? (
        <>
          <Explanation />
          <ChoiceForm current={data} />
        </>
      ) : (
        <p className="text-xs text-content-secondary">
          {t('geo_hub.consent.waiting', {
            defaultValue:
              'Addresses are not sent to a map service until a manager of this installation decides. Until then, place the project by clicking the map.',
          })}
        </p>
      )}
    </div>
  );
}

/** Current answer with a way to change it, for the Geo Hub admin page. */
export function GeocodingConsentPanel() {
  const { t } = useTranslation();
  const { data } = useConsent();
  const [editing, setEditing] = useState(false);
  if (!data) return null;

  const stateText: Record<GeocodingConsent['state'], string> = {
    unanswered: t('geo_hub.consent.state_unanswered', { defaultValue: 'Not decided yet. No address is sent.' }),
    allow: t('geo_hub.consent.state_allow', { defaultValue: 'Addresses are sent to the public OpenStreetMap services.' }),
    deny: t('geo_hub.consent.state_deny', { defaultValue: 'Addresses are not sent anywhere.' }),
    mirror: t('geo_hub.consent.state_mirror', { defaultValue: 'Addresses are sent to your own server.' }),
    env_disabled: t('geo_hub.consent.state_env_disabled', {
      defaultValue: 'Switched off by the deployment settings. No address is sent.',
    }),
    env_mirror: t('geo_hub.consent.state_env_mirror', {
      defaultValue: 'The deployment settings send addresses to your own server.',
    }),
  };

  return (
    <section className="space-y-3 rounded-xl border border-border-light bg-surface-primary p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
        <MapPin size={14} aria-hidden />
        {t('geo_hub.consent.panel_title', { defaultValue: 'Sending addresses to a map service' })}
      </h2>
      <Explanation />
      <p className="text-sm text-content-primary">
        {stateText[data.state]}
        {data.nominatim_url ? ` (${data.nominatim_url})` : ''}
      </p>
      {data.can_decide &&
        (editing || data.state === 'unanswered' ? (
          <ChoiceForm current={data} onDone={() => setEditing(false)} />
        ) : (
          <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
            {t('geo_hub.consent.change', { defaultValue: 'Change' })}
          </Button>
        ))}
    </section>
  );
}
