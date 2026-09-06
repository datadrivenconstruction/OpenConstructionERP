// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * MarketPackPanel - the regional pack a case expects, named and switchable
 * from the case itself.
 *
 * The case page already said a market's standards apply, and a chip beside the
 * title later said which pack carries them. Both stopped one step short of the
 * thing a reader actually wants at that moment: turning it on. Sending them to
 * the module registry to find the same pack in a list of eighteen is a correct
 * route and a poor one, because the reader has to carry the pack's name across
 * a page boundary and match it by eye.
 *
 * So the panel names the pack, says what it sets, and carries the activate
 * button. The button opens `PartnerPackApplyDialog`, the same dialog the pack
 * card opens, rather than a smaller copy of it. That dialog is where applying
 * a pack is made safe: a dry run of exactly what changes, an explicit confirm
 * for the modules it would switch off, and a streamed install with named
 * steps. A compact "apply" here would either skip that preview, which is the
 * confirm step itself, or duplicate it and drift from it.
 *
 * Where it sits is part of the design. It fills the foot of the process
 * column, which is the space the step strip leaves empty, so the two blocks of
 * that row end level instead of one trailing 76px above the other.
 *
 * Not every case has one, and the panel says so rather than vanishing.
 * Thirty-three of the eighty cases that name a market resolve no pack on a
 * released install: ten carry ES and no pack declares that country at all,
 * while thirteen German and ten Canadian cases point at packs that exist in
 * the source tree and are deliberately not distributed. Rendering nothing is
 * why a reader who filters the catalogue to Germany finds no install control
 * anywhere, on a build where thirteen cards each announce that German
 * standards apply: nothing on the screen separates "this case needs no pack"
 * from "the pack for your market is not in this build". What is still refused
 * is a plausible neighbour - German standards under a Spanish case would be
 * worse than either silence or a plain statement.
 *
 * The absence is only claimed once the server has answered. While the
 * installed list is in flight `data` is undefined and every market resolves to
 * nothing, so a panel that read `packs.length === 0` alone would put a false
 * line on every case page for as long as the request takes.
 *
 * The link is admin-only for the same reason the activate button is disabled
 * for everyone else: `/modules?tab=packs` carries the upload and rescan
 * controls, both `RequirePermission("admin")` server-side and both rendering
 * nothing for a viewer. Sending a viewer there would offer an action that
 * screen cannot give them.
 *
 * Every string here already existed in all locales before this component did.
 * `cases.regional_pack_for_market` in particular was left unread when the chip
 * replaced the old sentence, and this puts it back to work rather than adding
 * a synonym of it to forty-three files.
 */

import { Check, ShieldCheck, ExternalLink, Power } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { PartnerPackApplyDialog } from '@/features/modules/PartnerPackApplyDialog';
import { useInstalledPacks } from '@/shared/hooks/usePartnerPack';
import { marketCode, packNameSlug, packSummary, resolveMarketPacks } from '@/shared/lib/regionalPack';
import { Badge, Button, PackEmblem } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';

import { regionDisplayName } from './regions';

export interface MarketPackPanelProps {
  /** ISO 3166-1 alpha-2 for the case's market. Cases spell it upper case. */
  region: string | null | undefined;
  className?: string;
}

export function MarketPackPanel({ region, className = '' }: MarketPackPanelProps) {
  const { t, i18n } = useTranslation();
  const { data } = useInstalledPacks();
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';
  const [applyOpen, setApplyOpen] = useState(false);

  const { packs, applied } = useMemo(
    () => resolveMarketPacks(data?.installed ?? [], data?.active_slug, region),
    [data, region],
  );

  if (packs.length === 0) {
    const market = marketCode(region);
    // A case that names no market is not missing anything: most of the
    // catalogue is deliberately universal, and a line about packs on all of
    // them would be noise. `data` guards the other half: no answer yet, or a
    // failed request, is not evidence of an absence.
    if (!market || !data) return null;

    const marketName = regionDisplayName(market.toUpperCase(), i18n.language);
    const headline = t('cases.regional_pack_none_for_market', {
      defaultValue: 'No regional pack for {{market}} is installed here',
      market: marketName,
    });

    return (
      <section
        data-testid="market-pack-panel"
        data-pack-state="none"
        data-market={market}
        aria-label={headline}
        className={['rounded-xl border border-border bg-surface-secondary p-3', className].join(' ')}
      >
        <p className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
          {headline}
        </p>

        <p className="mt-1 text-xs leading-relaxed text-content-secondary">
          {t('dashboard.regional_pack_none_body', {
            defaultValue:
              'A regional pack sets up one market\u2019s prices, tax rules and standards for you, so you do not have to enter them by hand.',
          })}
        </p>

        {isAdmin && (
          <Link
            to="/modules?tab=packs"
            className="mt-2.5 inline-flex items-center gap-1 text-2xs font-medium text-oe-blue-text underline-offset-2 hover:underline"
          >
            <ExternalLink size={12} />
            {t('dashboard.regional_pack_choose', { defaultValue: 'Install a country pack' })}
          </Link>
        )}
      </section>
    );
  }

  // The applied pack when there is one, otherwise the first that serves this
  // market. Several can: us-california, us-costdata and us-texas all declare
  // US, and the rest stay one click away in the registry.
  const lead = applied ?? packs[0]!;
  const name = t(`modules.pp_name_${packNameSlug(lead.slug)}`, {
    defaultValue: lead.partner_name,
  });
  const summary = packSummary(lead.description);
  const accent = lead.branding.accent_color ?? lead.branding.primary_color;
  const isApplied = applied !== null;

  return (
    <section
      data-testid="market-pack-panel"
      data-pack-state={isApplied ? 'applied' : 'available'}
      data-pack-slug={lead.slug}
      aria-label={t('cases.regional_pack_for_market', {
        defaultValue: 'Regional pack: {{names}}',
        names: name,
      })}
      // Tinted rather than plain, so the row reads as strip plus panel rather
      // than as a second card of the same weight as the company comb. Alpha is
      // taken from `oe-blue` and `semantic-success`, never from the `-subtle`
      // tokens: those carry no alpha support and Tailwind emits nothing at all
      // for an alpha-modified form of them, which renders as no fill.
      className={[
        'rounded-xl border p-3',
        isApplied
          ? 'border-semantic-success/30 bg-semantic-success/5'
          : 'border-oe-blue/25 bg-oe-blue/5',
        className,
      ].join(' ')}
    >
      <div className="flex items-start gap-3">
        <PackEmblem pack={lead} size={38} />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <p className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('cases.regional_pack_for_market', {
                defaultValue: 'Regional pack: {{names}}',
                names: name,
              })}
            </p>
            {isApplied ? (
              <Badge variant="success" size="sm">
                <Check size={10} className="mr-0.5" />
                {t('modules.active', { defaultValue: 'Active' })}
              </Badge>
            ) : (
              !isAdmin && (
                <Badge variant="neutral" size="sm">
                  <ShieldCheck size={10} className="mr-0.5" />
                  {t('modules.admin_only', { defaultValue: 'Admin only' })}
                </Badge>
              )
            )}
          </div>

          {summary && (
            <p className="mt-1 text-xs leading-relaxed text-content-secondary">{summary}</p>
          )}

          {/* What the pack sets, in the same quiet line the pack card uses, so
              a reader who has seen one recognises the other. Data, not
              sentences: no key can be missing from a currency code. */}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-content-tertiary">
            <span className="font-mono">{lead.default_currency}</span>
            {lead.default_tax_template && (
              <>
                <span className="text-border">·</span>
                <span className="truncate font-mono">{lead.default_tax_template}</span>
              </>
            )}
            <span className="text-border">·</span>
            <span className="font-mono">v{lead.pack_version}</span>
            {lead.validation_rule_packs.length > 0 && (
              <>
                <span className="text-border">·</span>
                <span className="inline-flex items-center gap-1" style={{ color: accent }}>
                  <ShieldCheck size={11} />
                  {t('modules.partner_pack_standards', { defaultValue: 'Reference standards' })}
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {isApplied ? (
          <p className="inline-flex items-center gap-1.5 text-2xs font-medium text-content-secondary">
            <Check size={12} className="text-semantic-success" />
            {t('cases.regional_pack_in_use', {
              defaultValue: 'Regional pack in use: {{name}}',
              name,
            })}
          </p>
        ) : (
          <Button
            variant="primary"
            size="sm"
            icon={<Power size={14} />}
            disabled={!isAdmin}
            onClick={() => setApplyOpen(true)}
            title={t('cases.regional_pack_setup_hint', {
              defaultValue:
                'This case follows the standards of its market. Opens the pack that carries them, where you can switch it on.',
            })}
          >
            {t('modules.pack_activate', { defaultValue: 'Activate pack' })}
          </Button>
        )}

        {/* The registry stays one click away in both states: it is where the
            other packs for this market live, and where a reader can see what
            an applied pack configures without switching anything.

            Labelled with the registry's own name rather than `Set up`, which
            is what the chip used to say when a link was the only action on
            offer. Beside a button that says "Activate pack" the same words
            would read as a second way to do the same thing. */}
        <Link
          to={`/modules?tab=packs&pack=${encodeURIComponent(lead.slug)}`}
          className="inline-flex items-center gap-1 text-2xs font-medium text-oe-blue-text underline-offset-2 hover:underline"
        >
          <ExternalLink size={12} />
          {t('nav.modules', { defaultValue: 'Modules' })}
        </Link>
      </div>

      <PartnerPackApplyDialog
        open={applyOpen}
        onClose={() => setApplyOpen(false)}
        slug={lead.slug}
        partnerName={lead.partner_name}
      />
    </section>
  );
}
