// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// InsidePage - the "Inside track" backers-only panel.
//
// The perk donations buy is ACCESS TO INFORMATION, never a paywall on the
// AGPL code itself: a curated, single-page view of what just shipped (pulled
// straight from the same Changelog the /about page already renders, so this
// panel updates itself every release with zero extra writing) plus a short,
// plain-title roadmap list of what is coming next. Locked by default; a
// supporter access code (handed out after a donation) unlocks it and the
// unlock is remembered in localStorage on this device.

import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  Sparkles,
  Lock,
  Unlock,
  KeyRound,
  Heart,
  Github,
  Rocket,
  ArrowRight,
  ListChecks,
  ShieldCheck,
} from 'lucide-react';
import { Card, Badge, Button, Input, Breadcrumb } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { Changelog, getRecentReleases } from '@/features/about/Changelog';
import { useInsideAccess } from './useInsideAccess';
import { INSIDE_ROADMAP } from './roadmap';

const PAYPAL_DONATE_URL = 'https://www.paypal.com/donate/?hosted_button_id=DWBCLNLY2VWAA';
const GITHUB_SPONSORS_URL = 'https://github.com/sponsors/datadrivenconstruction';

export function InsidePage() {
  const { t } = useTranslation();
  const unlocked = useInsideAccess((s) => s.unlocked);

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[{ label: t('inside.breadcrumb', { defaultValue: 'Inside track' }) }]}
      />
      <PageHeader
        srTitle={t('inside.page_title', { defaultValue: 'Inside track' })}
        subtitle={t('inside.page_subtitle', {
          defaultValue:
            'A backers-only news panel: what just shipped and what is coming next, in one place.',
        })}
      />

      {unlocked ? <UnlockedPanel /> : <LockedTeaser />}
    </div>
  );
}

/* -- Locked state - teaser + code entry + donate CTA -------------------- */

function LockedTeaser() {
  const { t } = useTranslation();
  const tryUnlock = useInsideAccess((s) => s.tryUnlock);
  const [code, setCode] = useState('');
  const [error, setError] = useState(false);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    const ok = tryUnlock(code);
    setError(!ok);
    if (ok) setCode('');
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 items-stretch">
      {/* -- Left - teaser preview, blurred so it reads as a real preview -- */}
      <Card className="lg:col-span-3 overflow-hidden">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <Sparkles size={18} className="text-amber-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('inside.teaser_title', { defaultValue: 'What backers see first' })}
            </h2>
          </div>
          <div className="relative">
            <div className="pointer-events-none select-none blur-[3px] opacity-60">
              <TeaserPreviewList />
            </div>
            <div className="absolute inset-0 flex items-end justify-center bg-gradient-to-t from-surface-primary via-surface-primary/70 to-transparent pt-10">
              <div className="pb-2 flex items-center gap-2 text-xs font-medium text-content-secondary">
                <Lock size={13} />
                {t('inside.teaser_locked_hint', {
                  defaultValue: 'Enter a supporter code to unlock the full panel',
                })}
              </div>
            </div>
          </div>
        </div>
      </Card>

      {/* -- Right - code entry + donate CTA -- */}
      <Card className="lg:col-span-2">
        <div className="p-6 flex flex-col h-full">
          <div className="flex items-center gap-2 mb-2">
            <KeyRound size={18} className="text-oe-blue" />
            <h2 className="text-base font-semibold text-content-primary">
              {t('inside.unlock_title', { defaultValue: 'Enter supporter code' })}
            </h2>
          </div>
          <p className="text-xs text-content-secondary leading-relaxed mb-4">
            {t('inside.unlock_body', {
              defaultValue:
                'Donors get a supporter access code after donating. Enter it below to unlock the Inside track panel on this device.',
            })}
          </p>
          <form onSubmit={handleSubmit} className="space-y-2">
            <Input
              value={code}
              onChange={(e) => {
                setCode(e.target.value);
                if (error) setError(false);
              }}
              placeholder={t('inside.unlock_placeholder', {
                defaultValue: 'Supporter access code',
              })}
              error={
                error
                  ? t('inside.unlock_error', {
                      defaultValue: 'That code is not recognized. Check it and try again.',
                    })
                  : undefined
              }
              aria-label={t('inside.unlock_placeholder', {
                defaultValue: 'Supporter access code',
              })}
            />
            <Button type="submit" variant="primary" size="md" className="w-full">
              {t('inside.unlock_submit', { defaultValue: 'Unlock Inside track' })}
            </Button>
          </form>

          <div className="mt-5 pt-5 border-t border-border-light">
            <p className="text-xs font-semibold text-content-primary mb-1">
              {t('inside.no_code_title', { defaultValue: "Don't have a code yet?" })}
            </p>
            <p className="text-xs text-content-secondary leading-relaxed mb-3">
              {t('inside.no_code_body', {
                defaultValue:
                  'A donation of any size gets you a code by return. Donations keep the AGPL core free for everyone - the panel is the thank-you, never a paywall on the software itself.',
              })}
            </p>
            <div className="flex flex-wrap gap-2">
              <a href={PAYPAL_DONATE_URL} target="_blank" rel="noopener noreferrer">
                <Button variant="secondary" size="sm" icon={<Heart size={13} />}>
                  {t('inside.donate_paypal', { defaultValue: 'Donate with PayPal' })}
                </Button>
              </a>
              <a href={GITHUB_SPONSORS_URL} target="_blank" rel="noopener noreferrer">
                <Button variant="secondary" size="sm" icon={<Github size={13} />}>
                  {t('inside.donate_github', { defaultValue: 'Sponsor on GitHub' })}
                </Button>
              </a>
            </div>
          </div>

          <p className="mt-auto pt-4 text-2xs text-content-tertiary leading-relaxed">
            {t('inside.donate_no_paywall', {
              defaultValue:
                'The platform and its code stay free and open (AGPL-3.0) whether or not you unlock this panel.',
            })}
          </p>
        </div>
      </Card>
    </div>
  );
}

/** A muted, non-interactive stand-in for the real content, shown blurred
 *  behind the lock overlay so the teaser reads as a genuine preview instead
 *  of a placeholder box. */
function TeaserPreviewList() {
  const { t } = useTranslation();
  return (
    <div className="space-y-2.5">
      {[0, 1, 2].map((i) => (
        <div key={i} className="rounded-lg border border-border-light px-3.5 py-2.5">
          <div className="flex items-center gap-2">
            <Badge variant="success" size="sm">
              {t('inside.teaser_new_badge', { defaultValue: 'NEW' })}
            </Badge>
            <span className="h-2 w-16 rounded bg-surface-secondary" />
          </div>
          <div className="mt-2 h-2 w-full rounded bg-surface-secondary" />
          <div className="mt-1.5 h-2 w-4/5 rounded bg-surface-secondary" />
        </div>
      ))}
    </div>
  );
}

/* -- Unlocked state - real content --------------------------------------- */

function UnlockedPanel() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const lock = useInsideAccess((s) => s.lock);
  // Reuses the same changelog Changelog.tsx already renders on /about, so
  // this feed updates itself the moment a new release is added there - no
  // separate content for anyone to keep writing.
  const recent = getRecentReleases(6);

  return (
    <div className="space-y-5">
      <Card className="border-emerald-300/50 bg-gradient-to-br from-emerald-50/50 to-transparent dark:border-emerald-500/25 dark:from-emerald-950/20">
        <div className="p-4 flex items-center gap-3">
          <ShieldCheck size={18} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
          <p className="text-xs text-content-secondary leading-relaxed flex-1">
            {t('inside.unlocked_banner', {
              defaultValue:
                'Inside track unlocked on this device. Thank you for backing the project.',
            })}
          </p>
          <Button variant="ghost" size="sm" onClick={lock} icon={<Lock size={13} />}>
            {t('inside.relock', { defaultValue: 'Lock again' })}
          </Button>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 items-start">
        {/* -- Just shipped - sourced straight from the app changelog -- */}
        <Card className="lg:col-span-3">
          <div className="p-6">
            <div className="flex items-center gap-2 mb-1">
              <Unlock size={17} className="text-emerald-600 dark:text-emerald-400" />
              <h2 className="text-base font-semibold text-content-primary">
                {t('inside.shipped_title', { defaultValue: 'Just shipped' })}
              </h2>
              <Badge variant="success" size="sm">
                {t('inside.shipped_badge', { defaultValue: 'Backer view' })}
              </Badge>
            </div>
            <p className="text-xs text-content-secondary mb-4">
              {t('inside.shipped_subtitle', {
                defaultValue:
                  'The latest releases, collected here for backers. Same changelog the whole team can read on the About page.',
              })}
            </p>
            {recent.length > 0 ? (
              <Changelog maxEntries={6} />
            ) : (
              <p className="text-xs text-content-tertiary">
                {t('inside.shipped_empty', { defaultValue: 'No releases recorded yet.' })}
              </p>
            )}
            <button
              type="button"
              onClick={() => navigate('/about#changelog')}
              className="group mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-oe-blue hover:text-oe-blue-text transition-colors"
            >
              {t('inside.shipped_full_link', { defaultValue: 'See the full changelog' })}
              <ArrowRight size={12} className="transition-transform group-hover:translate-x-0.5" />
            </button>
          </div>
        </Card>

        {/* -- Coming next - short, plain-title roadmap list -- */}
        <Card className="lg:col-span-2">
          <div className="p-6">
            <div className="flex items-center gap-2 mb-1">
              <Rocket size={17} className="text-oe-blue" />
              <h2 className="text-base font-semibold text-content-primary">
                {t('inside.next_title', { defaultValue: 'Coming next' })}
              </h2>
            </div>
            <p className="text-xs text-content-secondary mb-4">
              {t('inside.next_subtitle', {
                defaultValue: 'Directions we are working toward - not a fixed promise or a date.',
              })}
            </p>
            <ul className="space-y-2">
              {INSIDE_ROADMAP.map((item) => (
                <li
                  key={item.id}
                  className="flex items-start gap-2 text-xs text-content-secondary"
                >
                  <ListChecks size={13} className="mt-0.5 shrink-0 text-oe-blue" />
                  <span>{t(item.titleKey, { defaultValue: item.titleDefault })}</span>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      </div>
    </div>
  );
}
