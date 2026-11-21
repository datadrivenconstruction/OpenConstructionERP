// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * About: which build you are running, and where the licence is stated.
 *
 * This page used to carry the product's marketing - a six-tile statistics row
 * (120K+ cost items, 47 countries, 180+ backend modules, 28 AI models), a
 * documentation card that deep-linked into the upstream repository's docs tree,
 * a full licence explainer with "You can / You must" columns and five badges
 * ("Free to use", "Open source", "Self-hosted", "No vendor lock-in"), a wall of
 * contributor and sponsor tiles rendered from their GitHub avatars, and a call
 * to action inviting the reader to go and contribute.
 *
 * All of that is gone. The owner ships this product as their own, and none of it
 * told a user anything they needed in order to use the software: the statistics
 * were claims, the documentation links pointed at somebody else's repository,
 * and the contributor wall was the upstream project's community, not this
 * installation's.
 *
 * What stays is what an About page is actually for. Which build is running, so a
 * support conversation starts from a fact. What the product does, in one line.
 * Whether this installation asks the internet which version is newest, because
 * that is a fact about the installation in front of you and not a preference of
 * whoever wrote the page. The release notes, which are product information about
 * the installation in front of you. And one link to /legal, which is the single place that states
 * the licence, the attribution notice and the source offer - it is not restated
 * here, because two places saying it is two places to keep correct.
 *
 * `data-changelog-anchor` is a contract, not decoration: WhatsNewCard scrolls to
 * it when the user asks to see the full changelog.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Card } from '@/shared/ui';
import { APP_NAME } from '@/shared/lib/brandName';
import { useUpdateCheckDisclosure } from '@/shared/lib/updateCheckDisclosure';
import { APP_VERSION } from '@/shared/lib/version';
import { Changelog, getRecentReleases } from './Changelog';

export function AboutPage() {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const recent = getRecentReleases(3);
  // One sentence, and the same one Settings shows next to the switch that decides
  // it: a disclosure written twice is a disclosure that drifts.
  const updateCheck = useUpdateCheckDisclosure();

  return (
    <div className="space-y-6" data-testid="about-page">
      {/* The build. Name, version, one line about what the product does, and the
          single link to where the licence is stated. */}
      <Card className="animate-card-in">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-content-primary">{APP_NAME}</h1>
            <p className="mt-1 font-mono text-sm text-content-secondary tabular-nums">
              v{APP_VERSION}
            </p>
            <p className="mt-3 max-w-2xl text-sm leading-relaxed text-content-secondary">
              {t('about.tagline', {
                defaultValue:
                  'Construction cost estimation, project management and resource control',
              })}
            </p>
            <p className="mt-2 max-w-2xl text-xs text-content-tertiary" data-testid="about-update-check">
              {updateCheck}
            </p>
          </div>
          <Link
            to="/legal"
            className="shrink-0 rounded-md border border-border-light px-3 py-1.5 text-sm text-content-secondary transition-colors hover:bg-surface-secondary hover:text-content-primary"
          >
            {t('legal.link', { defaultValue: 'Legal' })}
          </Link>
        </div>
      </Card>

      {/* Release notes for this installation. */}
      <Card className="animate-card-in" style={{ animationDelay: '80ms' }}>
        <div data-changelog-anchor className="scroll-mt-24">
          <h2 className="text-base font-semibold text-content-primary">
            {t('about.changelog_title', { defaultValue: 'Release notes' })}
          </h2>
        </div>
        <div className="mt-4">
          <Changelog maxEntries={expanded ? undefined : recent.length} />
        </div>
        {recent.length > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-4 text-sm font-medium text-oe-blue hover:underline"
          >
            {expanded
              ? t('about.changelog_show_less', { defaultValue: 'Show less' })
              : t('about.changelog_show_all', { defaultValue: 'Show all' })}
          </button>
        )}
      </Card>
    </div>
  );
}
