// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which server the desktop app talks to.
 *
 * The desktop build normally starts its own server and its own database on the
 * machine it is installed on, and that is still what happens on every install
 * where nobody has been here. An office that already runs one central
 * OpenConstructionERP does not want a second copy per desk, so this card is
 * where a person points their desktop app at that central server instead.
 *
 * It renders nothing outside the desktop shell. In a browser the question is
 * meaningless: the page is already being served by the server it is talking to,
 * and there is nothing to choose.
 *
 * THE TWO STATES THIS CARD HAS, AND WHY THE SECOND ONE IS NOT A FAILURE.
 *
 * In local mode the application is served by the launcher's own server on
 * loopback, and that origin is allowed to call the launcher, so this card is a
 * full editor.
 *
 * In remote mode the application is served by a server whose address a person
 * typed in. That origin is granted no native commands at all, deliberately: an
 * arbitrary address, granted the desktop command surface, is a different
 * product from the one we ship. So the launcher will refuse to answer this
 * page, and the card shows what it can see without asking anyone, which is its
 * own origin, plus the ways to change the setting that do not run through the
 * web page. That is the designed behaviour and the card says so rather than
 * looking broken.
 *
 * The card finds out which state it is in by making the call and seeing what
 * comes back, not by inspecting the hostname. Guessing from the hostname would
 * be a second, independent copy of the rule that lives in the capability files,
 * and the two would drift.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Server, Laptop, Cloud, Info, Loader2, Link2Off } from 'lucide-react';

import { Card, CardHeader, CardContent, CardFooter, Button, Input, Badge } from '@/shared/ui';
import {
  isTauri,
  getDesktopServerChoice,
  setDesktopServerChoice,
  type DesktopServerChoice,
} from '@/shared/lib/desktop';
import { useToastStore } from '@/stores/useToastStore';

export function DesktopServerCard() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [loading, setLoading] = useState(true);
  const [choice, setChoice] = useState<DesktopServerChoice | undefined>(undefined);
  const [mode, setMode] = useState<'local' | 'remote'>('local');
  const [url, setUrl] = useState('');
  const [error, setError] = useState<string | undefined>(undefined);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isTauri) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    void getDesktopServerChoice().then((answer) => {
      if (cancelled) return;
      setChoice(answer);
      if (answer) {
        setMode(answer.mode);
        // Only seed the field from a remote address. Seeding it from the
        // loopback address the launcher happens to be using today would put a
        // 127.0.0.1 URL in front of somebody who is trying to type their office
        // server, and it is the kind of prefilled value people save unread.
        setUrl(answer.mode === 'remote' ? answer.url : '');
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = useCallback(
    async (next: { mode: 'local' } | { mode: 'remote'; url: string } | null) => {
      setSaving(true);
      setError(undefined);
      const result = await setDesktopServerChoice(next);
      setSaving(false);
      if (!result.ok) {
        // The launcher validated the address and its refusal carries the
        // sentence saying why. Show that sentence beside the field rather than
        // a generic failure toast: it is the only part the user can act on.
        setError(
          result.reason ??
            t('settings.desktop_server_save_failed', {
              defaultValue: 'The desktop app could not save that setting.',
            }),
        );
        return;
      }
      const refreshed = await getDesktopServerChoice();
      setChoice(refreshed);
      addToast({
        type: 'success',
        title: t('settings.desktop_server_saved_title', { defaultValue: 'Server setting saved' }),
        message: t('settings.desktop_server_saved_body', {
          defaultValue: 'Close and reopen the app for this to take effect.',
        }),
      });
    },
    [addToast, t],
  );

  if (!isTauri) return null;

  const title = t('settings.desktop_server_title', { defaultValue: 'Application server' });
  const subtitle = t('settings.desktop_server_subtitle', {
    defaultValue: 'Run the server on this computer, or connect to one your organisation already runs',
  });

  if (loading) {
    return (
      <Card className="lg:col-span-2">
        <CardHeader title={title} subtitle={subtitle} />
        <CardContent>
          <div className="flex items-center gap-2 p-4 text-sm text-content-secondary">
            <Loader2 size={16} className="animate-spin" />
            {t('common.loading', { defaultValue: 'Loading...' })}
          </div>
        </CardContent>
      </Card>
    );
  }

  // The launcher would not answer. See the note at the top of this file: this
  // is what remote mode looks like from inside the page, and it is expected.
  if (!choice) {
    return (
      <Card className="lg:col-span-2">
        <CardHeader title={title} subtitle={subtitle} />
        <CardContent>
          <div className="flex flex-col gap-3 rounded-xl border border-border-light bg-surface-secondary/30 p-4">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
                <Cloud size={18} />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-content-primary">
                  {t('settings.desktop_server_managed_title', {
                    defaultValue: 'This app is connected to a server on your network',
                  })}
                </p>
                <p className="mt-0.5 break-all font-mono text-xs text-content-secondary">
                  {window.location.origin}
                </p>
              </div>
            </div>
            <p className="text-xs leading-relaxed text-content-secondary">
              {t('settings.desktop_server_managed_body', {
                defaultValue:
                  'The connection is managed by the desktop app itself, so it cannot be changed from this page. Use the tray icon menu of the desktop app to go back to a server on this computer, or ask whoever set this up.',
              })}
            </p>
            <p className="text-xs leading-relaxed text-content-tertiary">
              {t('settings.desktop_server_links_note', {
                defaultValue:
                  'Links to other websites are copied for you to paste rather than opened. The desktop app does not hand your browser to a server it did not start itself.',
              })}
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const dirty =
    mode !== choice.mode || (mode === 'remote' && url.trim() !== choice.url && url.trim() !== '');

  return (
    <Card className="lg:col-span-2">
      <CardHeader title={title} subtitle={subtitle} />
      <CardContent>
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border-light bg-surface-secondary/30 p-4">
            <Server size={16} className="shrink-0 text-content-tertiary" />
            <span className="text-sm text-content-secondary">
              {t('settings.desktop_server_current', { defaultValue: 'Currently using' })}
            </span>
            <span className="break-all font-mono text-sm font-semibold text-content-primary">
              {choice.url}
            </span>
            <Badge variant="neutral">{choice.source}</Badge>
          </div>

          <fieldset className="flex flex-col gap-2">
            <legend className="sr-only">{title}</legend>

            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-border-light p-4 hover:bg-surface-secondary/30">
              <input
                type="radio"
                name="oe-desktop-server-mode"
                className="mt-1"
                checked={mode === 'local'}
                onChange={() => {
                  setMode('local');
                  setError(undefined);
                }}
              />
              <Laptop size={18} className="mt-0.5 shrink-0 text-content-tertiary" />
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-content-primary">
                  {t('settings.desktop_server_mode_local', {
                    defaultValue: 'Run the server on this computer',
                  })}
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-content-secondary">
                  {t('settings.desktop_server_mode_local_hint', {
                    defaultValue:
                      'The normal setup. Your data stays on this machine and the app works with no network.',
                  })}
                </span>
              </span>
            </label>

            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-border-light p-4 hover:bg-surface-secondary/30">
              <input
                type="radio"
                name="oe-desktop-server-mode"
                className="mt-1"
                checked={mode === 'remote'}
                onChange={() => {
                  setMode('remote');
                  setError(undefined);
                }}
              />
              <Cloud size={18} className="mt-0.5 shrink-0 text-content-tertiary" />
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-content-primary">
                  {t('settings.desktop_server_mode_remote', {
                    defaultValue: 'Connect to a server on your network',
                  })}
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-content-secondary">
                  {t('settings.desktop_server_mode_remote_hint', {
                    defaultValue:
                      'Everyone works in the same projects on one shared server. Your colleagues see your changes.',
                  })}
                </span>
              </span>
            </label>
          </fieldset>

          {/* The links note is shown here as well as on the read-only panel, so
              that somebody meets the difference while they are deciding rather
              than only once they are living with it. */}
          {mode === 'remote' && (
            <>
              <Input
                label={t('settings.desktop_server_url_label', { defaultValue: 'Server address' })}
                placeholder="https://erp.example.com"
                value={url}
                error={error}
                hint={t('settings.desktop_server_url_hint', {
                  defaultValue:
                    'The full address, starting with http:// or https://. Ask whoever runs the server if you do not know it.',
                })}
                onChange={(e) => {
                  setUrl(e.target.value);
                  setError(undefined);
                }}
              />
              <p className="flex items-start gap-2 text-xs leading-relaxed text-content-tertiary">
                <Link2Off size={14} className="mt-0.5 shrink-0" />
                {t('settings.desktop_server_links_note', {
                  defaultValue:
                    'Links to other websites are copied for you to paste rather than opened. The desktop app does not hand your browser to a server it did not start itself.',
                })}
              </p>
            </>
          )}

          {mode === 'local' && error && (
            <p className="text-xs text-semantic-error" role="alert">
              {error}
            </p>
          )}

          <p className="flex items-start gap-2 text-xs leading-relaxed text-content-tertiary">
            <Info size={14} className="mt-0.5 shrink-0" />
            {t('settings.desktop_server_restart_note', {
              defaultValue:
                'A change here takes effect the next time you open the app, so that nothing you have open now is left belonging to the previous server.',
            })}
          </p>
        </div>
      </CardContent>
      <CardFooter>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            disabled={saving || !dirty || (mode === 'remote' && url.trim() === '')}
            onClick={() => {
              void save(mode === 'local' ? { mode: 'local' } : { mode: 'remote', url: url.trim() });
            }}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
          {choice.fromUserSetting && (
            <Button
              variant="secondary"
              size="sm"
              disabled={saving}
              onClick={() => {
                void save(null);
              }}
            >
              {/* Clearing hands the decision back to the environment variable
                  and the file an administrator deploys. On a managed machine it
                  is the way back to being managed, and without it a user who
                  once chose could never return. */}
              {t('settings.desktop_server_clear', { defaultValue: 'Use the default for this computer' })}
            </Button>
          )}
        </div>
      </CardFooter>
    </Card>
  );
}

export default DesktopServerCard;
