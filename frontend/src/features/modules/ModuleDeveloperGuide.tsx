// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ModuleDeveloperGuide - in-app, readable guide for building your own module.
 * The body is authored as Markdown (moduleDeveloperGuide.md) and rendered with
 * the shared <Markdown> component, so the content stays clear and easy to edit
 * and reads the same here as it does on GitHub. Mirrors the repo's MODULES.md.
 *
 * Layout: this is a long docs page, so on wide screens it reads as two columns.
 * The reading column is width-constrained (~76ch) so the card background hugs
 * the text instead of stretching across the whole page, and the space that
 * used to sit empty on the right carries a sticky "On this page" table of
 * contents. Below xl the TOC drops away and the guide reads as a single column.
 */

import { useEffect, useState, type MouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { ArrowLeft } from 'lucide-react';
import { Breadcrumb, Card, Markdown } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import guideMarkdown from './moduleDeveloperGuide.md?raw';

/**
 * Slug for a heading anchor. This MUST stay identical to the slugify() the
 * shared <Markdown> renderer uses for its heading ids, otherwise the table of
 * contents would link to anchors that do not exist.
 */
function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/`/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');
}

interface GuideSection {
  id: string;
  text: string;
}

/**
 * The top-level (##) sections of the guide, parsed once from the Markdown
 * source so the on-this-page rail never drifts out of sync with the content.
 * Sub-steps (### ...) are left out on purpose to keep the rail scannable.
 */
const GUIDE_SECTIONS: GuideSection[] = guideMarkdown
  .split('\n')
  .map((line) => /^##\s+(.+?)\s*$/.exec(line))
  .filter((match): match is RegExpExecArray => match !== null)
  .map((match) => {
    const heading = (match[1] ?? '').trim();
    return { id: slugify(heading), text: heading.replace(/`/g, '') };
  })
  .filter((section) => section.id.length > 0);

export function ModuleDeveloperGuide() {
  const { t } = useTranslation();
  const [activeId, setActiveId] = useState<string>('');

  // Deep-link support: when opened with a #hash (e.g. the Partner Packs tab
  // links to #partner-packs), scroll that section into view after render. The
  // Markdown heading ids are slugs of the heading text, so "## Partner Packs"
  // becomes #partner-packs.
  useEffect(() => {
    if (typeof window === 'undefined' || !window.location.hash) return;
    try {
      const el = document.querySelector(window.location.hash);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch {
      // Ignore an invalid selector from a malformed hash.
    }
  }, []);

  // Scroll-spy: highlight the section the reader is currently on in the "On
  // this page" rail. The rootMargin pulls the activation line just below the
  // sticky header so the highlighted item matches the heading at the top of
  // the viewport.
  useEffect(() => {
    if (GUIDE_SECTIONS.length === 0) return;
    const headings = GUIDE_SECTIONS.map((section) => document.getElementById(section.id)).filter(
      (el): el is HTMLElement => el !== null,
    );
    if (headings.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActiveId(entry.target.id);
        }
      },
      { rootMargin: '-76px 0px -70% 0px', threshold: 0 },
    );
    headings.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  const handleTocClick = (event: MouseEvent<HTMLAnchorElement>, id: string): void => {
    const el = document.getElementById(id);
    if (!el) return; // fall back to the browser's native anchor jump
    event.preventDefault();
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setActiveId(id);
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', `#${id}`);
    }
  };

  const onThisPageLabel = t('modules.dev_guide_on_this_page', { defaultValue: 'On this page' });

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.modules', 'Modules'), to: '/modules' },
          { label: t('modules.dev_guide', 'Developer guide') },
        ]}
      />

      <PageHeader
        srTitle={t('modules.dev_guide_title', { defaultValue: 'Build your own module' })}
        subtitle={t('modules.dev_guide_subtitle', {
          defaultValue:
            'A practical, 10-minute walkthrough for adding business features to OpenConstructionERP.',
        })}
        actions={
          <Link
            to="/modules"
            className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-oe-blue transition-colors"
          >
            <ArrowLeft size={12} />
            {t('modules.back_to_modules', { defaultValue: 'Back to Modules & Marketplace' })}
          </Link>
        }
      />

      {/* Two-column reading layout on wide screens: a width-constrained card so
          the background hugs the text, plus a sticky table of contents in the
          space that used to sit empty. Collapses to a single column below xl.
          The row keeps the default align-items:stretch so the <aside> matches
          the card's height - that tall containing block is what lets the nav
          inside it actually stay pinned (sticky) while the reader scrolls. */}
      <div className="flex flex-col gap-x-10 gap-y-6 xl:flex-row">
        <Card padding="none" className="min-w-0 max-w-[76ch] flex-1 p-6 md:p-8">
          <Markdown source={guideMarkdown} />
        </Card>

        {GUIDE_SECTIONS.length > 0 && (
          <aside className="hidden shrink-0 xl:block xl:w-64">
            <nav
              aria-label={onThisPageLabel}
              className="sticky top-20 max-h-[calc(100vh_-_7rem)] overflow-y-auto overscroll-contain pr-2"
            >
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                {onThisPageLabel}
              </p>
              <ul className="space-y-0.5 border-l border-border-light">
                {GUIDE_SECTIONS.map((section) => {
                  const active = activeId === section.id;
                  return (
                    <li key={section.id}>
                      <a
                        href={`#${section.id}`}
                        onClick={(event) => handleTocClick(event, section.id)}
                        aria-current={active ? 'location' : undefined}
                        className={clsx(
                          '-ml-px block border-l-2 py-1 pl-3 text-sm leading-snug transition-colors',
                          active
                            ? 'border-oe-blue font-medium text-oe-blue'
                            : 'border-transparent text-content-tertiary hover:border-border hover:text-content-primary',
                        )}
                      >
                        {section.text}
                      </a>
                    </li>
                  );
                })}
              </ul>
            </nav>
          </aside>
        )}
      </div>
    </div>
  );
}

export default ModuleDeveloperGuide;
