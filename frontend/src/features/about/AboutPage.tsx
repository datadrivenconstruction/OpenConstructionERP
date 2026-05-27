/**
 * AboutPage — Application info, author, license, consulting services.
 */

import { Trans, useTranslation } from 'react-i18next';
import {
  Mail, Shield, BookOpen, Users, Award,
  Briefcase, Globe, ExternalLink,
  Linkedin, Youtube, Star, Coffee, Rocket, ArrowRight, Handshake,
  Github, MessageCircle,
} from 'lucide-react';
import { Card, Button, Badge } from '@/shared/ui';
import { APP_VERSION } from '@/shared/lib/version';
import { UpdateNotification } from '@/shared/ui/UpdateChecker';
import { Changelog } from './Changelog';

export function AboutPage() {
  const { t } = useTranslation();

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 space-y-6 animate-fade-in">
      {/* Header — two columns on wide screens: identity on the left,
          update-availability notification on the right so users can
          spot a new release at a glance. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 py-6 items-center">

        {/* ── Left column — project identity (left-aligned on wide) ── */}
        <div className="text-center lg:text-left">
          <a
            href="https://openconstructionerp.com?utm_source=app&utm_medium=about"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-oe-blue hover:text-oe-blue-text transition-colors mb-4"
          >
            <Globe size={13} />
            openconstructionerp.com
            <ExternalLink size={11} />
          </a>
          <div className="flex items-center justify-center lg:justify-start gap-2 mb-4">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
            </span>
            <span className="text-xs font-semibold uppercase tracking-widest text-emerald-600">Open Source</span>
          </div>
          <h1 className="text-3xl font-bold text-content-primary tracking-tight">OpenConstructionERP</h1>
          <p className="mt-2 text-base text-content-secondary">
            {t('about.tagline', { defaultValue: 'The #1 open-source platform for construction cost estimation, project management and resource control' })}
          </p>
          <div className="mt-3 flex items-center justify-center lg:justify-start gap-3 text-sm text-content-tertiary">
            <span className="font-mono">v{APP_VERSION}</span>
            <span>&middot;</span>
            <span>2026</span>
            <span>&middot;</span>
            <Badge variant="blue" size="sm">AGPL-3.0</Badge>
          </div>
        </div>

        {/* ── Right column — update notification + recent releases ──
            UpdateNotification renders its own card; the recent-releases
            mini-list lives below it so the right column visually matches
            the left identity block's height on wide screens. */}
        <div className="flex flex-col gap-3">
          <UpdateNotification forceShow hideDismiss />

          {/* Recent releases — last 3 published versions with date so
              users can see the cadence at a glance without scrolling
              into the Changelog further down. */}
          <div className="rounded-xl border border-border-light bg-surface-secondary/40 px-4 py-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('about.header_recent_label', { defaultValue: 'Recent releases' })}
              </p>
              <a
                href="#changelog"
                className="text-2xs text-oe-blue hover:underline"
                onClick={(e) => {
                  e.preventDefault();
                  const changelog = document.querySelector('[data-changelog-anchor]');
                  if (changelog) changelog.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }}
              >
                {t('about.header_recent_more', { defaultValue: 'View all →' })}
              </a>
            </div>
            <ul className="space-y-1.5">
              {[
                { v: '3.12.0', date: '2026-05-20', note: t('about.recent_3_12_0', { defaultValue: 'Wave 5/6/7 pro-grade — BOQ + Cost Intel + Clash A4 + Files CDE' }) },
                { v: '3.11.0', date: '2026-05-20', note: t('about.recent_3_11_0', { defaultValue: 'Wave 3/4 modules · Validation@Import · X84 export · /about redesign' }) },
                { v: '3.10.0', date: '2026-05-19', note: t('about.recent_3_10_0', { defaultValue: '/files ACC-grade wave · Clash collab/metadata · match polish' }) },
              ].map(r => (
                <li key={r.v} className="flex items-start gap-2 text-2xs leading-snug">
                  <span className="shrink-0 inline-flex items-center rounded-md bg-oe-blue/10 text-oe-blue font-mono font-semibold px-1.5 py-0.5">
                    v{r.v}
                  </span>
                  <span className="shrink-0 font-mono text-content-quaternary">{r.date}</span>
                  <span className="min-w-0 flex-1 truncate text-content-secondary" title={r.note}>
                    {r.note}
                  </span>
                </li>
              ))}
            </ul>
          </div>

        </div>
      </div>

      {/* Two-card band: Platform Capabilities + Community.
          Each is its own Card so they visually read as separate blocks; both
          carry h-full + flex-col so the row stretches to the tallest sibling
          and the inside content fills the matched height. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">

      {/* ── Card 1: Platform Capabilities ── */}
      <Card className="animate-card-in h-full flex flex-col" style={{ animationDelay: '50ms' }}>
        <div className="p-6 flex flex-col flex-1">
          <div className="flex items-center gap-2 mb-4">
            <Award size={18} className="text-amber-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('about.platform_title', { defaultValue: 'Platform Capabilities' })}
            </h2>
          </div>
          {/* Stats — one row on wide screens (6 tiles × 1 row) so the card
              stays compact and lines up vertically with the right-hand
              Community card. Smaller tile padding + value font keep the
              shorter tile readable at narrower widths. */}
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2.5">
            {[
              { value: '55K+', label: t('about.stat_costs', { defaultValue: 'Cost Items (CWICR)' }) },
              { value: '24', label: t('about.stat_langs', { defaultValue: 'Languages' }) },
              { value: '48', label: t('about.stat_regions', { defaultValue: 'Regional Databases' }) },
              { value: '6', label: t('about.stat_cad_formats', { defaultValue: 'CAD/BIM formats supported' }) },
              { value: '100+', label: t('about.stat_modules', { defaultValue: 'Backend modules' }) },
              { value: '12', label: t('about.stat_sections', { defaultValue: 'Menu sections' }) },
            ].map((s, i) => (
              <div key={i} className="text-center rounded-xl bg-surface-secondary/50 px-2 py-3">
                <div className="text-xl font-bold text-content-primary leading-none">{s.value}</div>
                <div className="text-2xs text-content-tertiary mt-1.5 leading-snug">{s.label}</div>
              </div>
            ))}
          </div>
          <p className="mt-auto pt-4 text-sm text-content-secondary leading-relaxed">
            {t('about.platform_desc', { defaultValue: 'OpenConstructionERP covers the full construction estimation workflow — BOQ editing, 4D scheduling, 5D cost modeling, AI-powered estimation, CAD/BIM quantity takeoff (RVT, IFC, DWG, DGN), tendering, and reporting. Supports regional classification standards and custom schemas.' })}
          </p>
        </div>
      </Card>

      {/* ── Card 2: Community — feedback channels.
          Uses the same blue-tinted gradient the old embedded block had, so
          the visual identity carries over but as its own bordered Card. ── */}
      <Card
        padding="none"
        className="animate-card-in h-full flex flex-col overflow-hidden border-oe-blue/20 bg-gradient-to-br from-oe-blue/5 via-transparent to-blue-50/40 dark:from-blue-950/20 dark:via-transparent dark:to-slate-900/30"
        style={{ animationDelay: '75ms' }}
      >
        <div className="p-6 flex flex-col flex-1">
            <div className="flex items-start gap-3 mb-4">
              {/* Plain Stroke — community icon, no chip wrapper. r-cleanup 2026-05-11. */}
              <MessageCircle size={20} strokeWidth={1.75} className="shrink-0 mt-0.5 text-oe-blue" />
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('about.community_title', { defaultValue: 'Join the community — your feedback shapes the roadmap' })}
                </h3>
                <p className="text-xs text-content-secondary mt-1 leading-relaxed">
                  {t('about.community_desc', {
                    defaultValue:
                      'Share what works, what breaks, and what you want next. Every release in the changelog started as a user request. Pick the channel you already use — we read all three.',
                  })}
                </p>
              </div>
            </div>

            {/* Social channels — Telegram is featured on its own row (it's the
                primary live-support channel) so the chat invite reads first.
                LinkedIn and X follow on their own rows so the Community card
                stretches vertically to match the Platform Capabilities card
                on wide screens. Each tile carries a 2-line copy block instead
                of a 1-line truncated string. */}
            <div className="flex flex-col gap-2.5">

              {/* Featured row — Telegram, primary live channel. */}
              <a
                href="https://t.me/datadrivenconstruction"
                target="_blank"
                rel="noopener noreferrer"
                className="group flex items-center gap-3 rounded-lg border border-[#26A5E4]/25 bg-[#26A5E4]/[0.04] px-3.5 py-3 hover:border-[#26A5E4]/50 hover:bg-[#26A5E4]/[0.08] transition-all"
              >
                <span className="shrink-0 h-10 w-10 rounded-lg bg-[#26A5E4]/15 text-[#26A5E4] flex items-center justify-center">
                  <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5" aria-hidden>
                    <path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71l-4.14-3.06-1.99 1.93c-.23.23-.42.42-.83.42z"/>
                  </svg>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-content-primary leading-tight">
                      Telegram
                    </p>
                    <span className="inline-flex items-center rounded-md bg-[#26A5E4]/15 text-[#26A5E4] text-2xs font-semibold px-1.5 py-0.5">
                      {t('about.community_tg_badge', { defaultValue: 'Live' })}
                    </span>
                  </div>
                  <p className="text-xs text-content-secondary mt-0.5 leading-snug">
                    {t('about.community_telegram_v2', { defaultValue: 'Fastest replies from the maintainers — questions, ideas, bug reports, partnerships.' })}
                  </p>
                </div>
                <ExternalLink size={13} className="text-content-quaternary group-hover:text-[#26A5E4] shrink-0" />
              </a>

              {/* LinkedIn + X — paired on one row so the Community card stays
                  compact and matches the Platform Capabilities card's height. */}
              <div className="grid grid-cols-2 gap-2.5">
                <a
                  href="https://www.linkedin.com/company/78381569"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-center gap-2.5 rounded-lg border border-border-light bg-surface-primary px-3 py-2.5 hover:border-[#0A66C2]/50 hover:bg-[#0A66C2]/[0.04] transition-all"
                >
                  <span className="shrink-0 h-9 w-9 rounded-lg bg-[#0A66C2]/10 text-[#0A66C2] flex items-center justify-center">
                    <Linkedin size={16} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold text-content-primary leading-tight">
                      LinkedIn
                    </p>
                    <p className="text-2xs text-content-tertiary mt-0.5 leading-snug">
                      {t('about.community_linkedin_short', { defaultValue: 'Articles + industry posts' })}
                    </p>
                  </div>
                </a>

                <a
                  href="https://x.com/datadrivenconst"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-center gap-2.5 rounded-lg border border-border-light bg-surface-primary px-3 py-2.5 hover:border-slate-700/50 hover:bg-slate-900/[0.04] dark:hover:border-slate-300/40 transition-all"
                >
                  <span className="shrink-0 h-9 w-9 rounded-lg bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900 flex items-center justify-center">
                    <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5" aria-hidden>
                      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231 5.45-6.231zm-1.161 17.52h1.833L7.084 4.126H5.117l11.966 15.644z"/>
                    </svg>
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold text-content-primary leading-tight">
                      X / Twitter
                    </p>
                    <p className="text-2xs text-content-tertiary mt-0.5 leading-snug">
                      {t('about.community_x_short', { defaultValue: 'Release announcements' })}
                    </p>
                  </div>
                </a>
              </div>
            </div>

            <p className="mt-auto pt-4 text-[11px] text-content-tertiary text-center">
              {t('about.community_cta', {
                defaultValue:
                  'Have a feature idea? A bug? A workflow we haven\'t thought of? Drop a message — we reply.',
              })}
            </p>
        </div>
      </Card>

      </div>
      {/* /Two-card band */}

      {/* About the project — founder's note (left) + DDC ecosystem (right).
          Two-column inside one Card so heights stay synced on wide screens.
          On narrow screens the right column stacks below. */}
      <Card className="animate-card-in" style={{ animationDelay: '150ms' }}>
        <div className="p-6 grid grid-cols-1 lg:grid-cols-5 gap-x-8 gap-y-6">
          {/* ── Left column — narrative (3 of 5 cols on wide screens) ── */}
          <div className="lg:col-span-3">
          {/* Block heading — short, sets context for the bio below. */}
          <div className="mb-5 flex items-center gap-2">
            <BookOpen size={18} className="text-oe-blue" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('about.story_title', { defaultValue: 'About the project' })}
            </h2>
          </div>
          <p className="mb-5 text-sm text-content-secondary">
            {t('about.story_subtitle', { defaultValue: 'Why OpenConstructionERP exists and where it is heading.' })}
          </p>
          {/* Bio — line length now governed by the col width itself. */}
          <div>
            <div className="min-w-0 flex-1">
              <div className="space-y-3 text-sm text-content-secondary leading-relaxed">
                <p>
                  {t('about.founder_bio_p1', {
                    defaultValue:
                      'Over the past ten years, I have been deeply involved in resource management for construction projects. This journey inevitably led me to study the history of the technologies that have shaped the industry — from the earliest attempts at design automation to modern ERP platforms (the series of articles "The Lobbyists\' Wars and the Development of BIM" and "The History of the BIM Map"). Without understanding where we came from, it is impossible to see where we are going.',
                  })}
                </p>
                <p>
                  <Trans
                    i18nKey="about.founder_bio_p2"
                    defaults='Over the years, dozens of articles have come off my desk, read by millions of professionals around the world. At the same time, I&rsquo;ve consulted with major construction and consulting firms, developers, and software vendors themselves on data management in projects — helping them navigate processes where data is not a byproduct but the foundation for decision-making. This work gave me a rare opportunity to see the industry from both sides: through the eyes of those who create the tools and through the eyes of those who use them in real projects every day. Many of these observations and reflections are collected in my book <book>Data-Driven Construction</book>, which is now available in 16 languages — <books>datadrivenconstruction.io/books</books>.'
                    components={{
                      book: (
                        <a
                          href="https://datadrivenconstruction.io/books"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-oe-blue hover:underline italic font-medium"
                        />
                      ),
                      books: (
                        <a
                          href="https://datadrivenconstruction.io/books"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-oe-blue hover:underline"
                        />
                      ),
                    }}
                  />
                </p>
                <p>
                  <Trans
                    i18nKey="about.founder_bio_p3"
                    defaults='Two other things have kept me busy: helping non-developers get into proprietary formats that were never meant to be opened, and finding a cleaner way to describe construction work through a resource model. These efforts have resulted in free tools — <cad>DDC CAD/BIM data converters</cad> (Revit, IFC, DWG, DGN → structured data), <gh>available on GitHub</gh>, and the multilingual <cwicr>CWICR database</cwicr> of construction works and resources — over 55,000 items in 11 languages, published as <cwicr>OpenConstructionEstimate-DDC-CWICR</cwicr>. All of this was a necessary step toward an idea I&rsquo;ve been pursuing for the past decade — an open-source modular ERP for the construction industry.'
                    components={{
                      cad: (
                        <a
                          href="https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-oe-blue hover:underline font-medium"
                        />
                      ),
                      gh: (
                        <a
                          href="https://github.com/datadrivenconstruction"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-oe-blue hover:underline"
                        />
                      ),
                      cwicr: (
                        <a
                          href="https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-oe-blue hover:underline font-medium"
                        />
                      ),
                    }}
                  />
                </p>
                <blockquote className="my-4 rounded-r-lg border-l-4 border-oe-blue bg-oe-blue/[0.04] py-3 px-4 text-[15px] italic text-content-primary leading-relaxed">
                  {t('about.founder_bio_p4', {
                    defaultValue:
                      "The recent generation of AI tooling finally made it feasible to consolidate that work — methodology, data models, and prior implementations — into a single platform. It's now public and open source.",
                  })}
                </blockquote>
                <p className="border-l-2 border-oe-blue/40 pl-3 italic text-content-primary">
                  {t('about.founder_bio_p5', {
                    defaultValue:
                      'Progress is born from dialogue — from the clash of perspectives and openness to new approaches. I would be grateful if you would be willing to participate in this conversation on the inevitable Uberization of the construction industry and the transparency of cost and time estimation processes for construction projects.',
                  })}
                </p>
              </div>
              {/* Author attribution — moved to the bottom of the bio per request. */}
              <div className="mt-5 flex items-center gap-3 border-t border-border-light pt-4">
                <img
                  src="/brand/artem-boiko-avatar.png"
                  alt={t('about.founder_name', { defaultValue: 'Artem Boiko' })}
                  className="h-12 w-12 shrink-0 rounded-xl object-cover bg-gradient-to-br from-slate-50 to-blue-50 dark:from-slate-800 dark:to-slate-900 ring-1 ring-border-light shadow-sm"
                  loading="lazy"
                />
                <div className="min-w-0 flex-1">
                  <h3 className="text-base font-bold text-content-primary leading-tight">
                    {t('about.founder_name', { defaultValue: 'Artem Boiko' })}
                  </h3>
                  <p className="text-xs text-oe-blue font-medium mt-0.5">
                    {t('about.founder_role', { defaultValue: 'Consultant for Automation & Data in Construction' })}
                  </p>
                </div>
              </div>
              {/* Social buttons removed — the same links live in the right
                  column's "Find us across the network" row, so the bio side
                  stays clean and the social channels are not duplicated. */}
            </div>
          </div>
          </div>
          {/* /Left column */}

          {/* ── Right column — DDC ecosystem (2 of 5 cols on wide screens) ──
              Three subsections, matching the "Built on DataDrivenConstruction"
              band on openconstructionerp.com:
                1. Flagship products (datadrivenconstruction.io)
                2. Open source on GitHub
                3. Find us across the network (social) */}
          <aside className="lg:col-span-2 lg:border-l lg:border-border-light lg:pl-8 flex flex-col h-full">
            <div className="mb-5 flex items-center gap-2">
              <Globe size={16} className="text-oe-blue" />
              <h3 className="text-sm font-semibold text-content-primary">
                {t('about.ddc_ecosystem_title', { defaultValue: 'DDC Ecosystem' })}
              </h3>
            </div>
            <p className="text-xs text-content-tertiary mb-6">
              {t('about.ddc_ecosystem_subtitle', { defaultValue: 'Projects mentioned above — every one is open-source or has a free tier.' })}
            </p>

            {/* ── Subsection 1: Flagship products ── */}
            <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('about.ddc_flagship_label', { defaultValue: 'Flagship products · datadrivenconstruction.io' })}
            </p>
            <ul className="mb-6 space-y-2.5">
              {[
                { href: 'https://datadrivenconstruction.io', label: 'DataDrivenConstruction', desc: t('about.ddc_link_lab', { defaultValue: 'Lab homepage — research & consulting' }) },
                { href: 'https://datadrivenconstruction.io/books/', label: 'DDC Guidebook', desc: t('about.ddc_link_book', { defaultValue: 'Reference reading, free, 16 languages' }) },
                { href: 'https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto', label: 'CAD-BIM Converter', desc: t('about.ddc_link_cad', { defaultValue: 'Pipeline: Revit · IFC · DWG · DGN → data' }) },
                { href: 'https://datadrivenconstruction.io/excel-plugin/', label: 'DDC Excel Plugin', desc: t('about.ddc_link_excel', { defaultValue: 'Spreadsheet bridge — pull live data into Excel' }) },
              ].map(item => (
                <li key={item.href}>
                  <a
                    href={item.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex items-start gap-3 rounded-lg border border-border-light bg-surface-secondary/40 px-3.5 py-3.5 hover:border-oe-blue/40 hover:bg-oe-blue/[0.04] transition-all"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-content-primary leading-tight group-hover:text-oe-blue transition-colors">
                        {item.label}
                      </p>
                      <p className="text-[11px] text-content-tertiary mt-0.5 leading-snug">
                        {item.desc}
                      </p>
                    </div>
                    <ArrowRight size={14} className="mt-1 shrink-0 text-content-quaternary group-hover:text-oe-blue group-hover:translate-x-0.5 transition-all" />
                  </a>
                </li>
              ))}
            </ul>

            {/* ── Subsection 2: Open source on GitHub ── */}
            <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('about.ddc_oss_label', { defaultValue: 'Open source on GitHub · @datadrivenconstruction' })}
            </p>
            <ul className="mb-6 space-y-2.5">
              {[
                { href: 'https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto', label: 'cad2data Pipeline', desc: t('about.ddc_gh_cad2data', { defaultValue: 'Revit · IFC · DWG · DGN → structured quantities' }) },
                { href: 'https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR', label: 'OpenConstructionEstimate', desc: t('about.ddc_gh_cwicr', { defaultValue: '55,000+ cost items · 24 languages · 48 regions' }) },
                { href: 'https://github.com/datadrivenconstruction', label: 'DDC Skills for AI Agents', desc: t('about.ddc_gh_skills', { defaultValue: 'Tool definitions & prompts for LLM agents' }) },
              ].map(item => (
                <li key={item.href}>
                  <a
                    href={item.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex items-start gap-3 rounded-lg border border-border-light bg-surface-secondary/40 px-3.5 py-3.5 hover:border-oe-blue/40 hover:bg-oe-blue/[0.04] transition-all"
                  >
                    <Github size={14} className="mt-0.5 shrink-0 text-content-tertiary group-hover:text-content-primary transition-colors" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-content-primary leading-tight group-hover:text-oe-blue transition-colors">
                        {item.label}
                      </p>
                      <p className="text-[11px] text-content-tertiary mt-0.5 leading-snug">
                        {item.desc}
                      </p>
                    </div>
                    <ArrowRight size={14} className="mt-1 shrink-0 text-content-quaternary group-hover:text-oe-blue group-hover:translate-x-0.5 transition-all" />
                  </a>
                </li>
              ))}
            </ul>

            {/* ── Subsection 3: Across the network — sticks to bottom via
                mt-auto so the right column visually fills the same height
                as the left bio + attribution. ── */}
            <div className="mt-auto">
              <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('about.ddc_network_label', { defaultValue: 'Find us across the network' })}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {[
                  { href: 'https://github.com/datadrivenconstruction', icon: Github, label: 'GitHub' },
                  { href: 'https://datadrivenconstruction.io', icon: Globe, label: 'Website' },
                  { href: 'https://www.linkedin.com/company/78381569', icon: Linkedin, label: 'LinkedIn' },
                  { href: 'https://www.youtube.com/@datadrivenconstruction', icon: Youtube, label: 'YouTube' },
                  { href: 'https://t.me/datadrivenconstruction', icon: MessageCircle, label: 'Telegram' },
                ].map(({ href, icon: Icon, label }) => (
                  <a
                    key={href}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={label}
                    aria-label={label}
                    className="group flex h-11 w-11 items-center justify-center rounded-lg border border-border-light bg-surface-secondary/40 hover:border-oe-blue/40 hover:bg-oe-blue/[0.06] transition-all"
                  >
                    <Icon size={17} className="text-content-tertiary group-hover:text-oe-blue transition-colors" />
                  </a>
                ))}
              </div>
            </div>
          </aside>
          {/* /Right column */}
        </div>
      </Card>

      {/* Consulting Services — matches the "Build 01 / Workshops 02 / Consulting 03"
          structure on openconstructionerp.com so users coming from the marketing
          page see the same offering shape inside the product. */}
      <Card>
        <div className="p-6">
          <div className="flex items-center gap-2 mb-2">
            <Briefcase size={18} className="text-oe-blue" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('about.services_title', { defaultValue: 'Consulting & Professional Services' })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary leading-relaxed mb-5 max-w-3xl">
            {t('about.services_desc_v2', { defaultValue: 'Need a custom build, a workshop, or an outside expert on data + cost workflows? Data Driven Construction delivers three engagement shapes — pick what fits and we scope from there.' })}
          </p>

          {/* Three numbered service cards — Build · Workshops · Consulting */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              {
                num: '01',
                icon: Rocket,
                title: t('about.svc_build_title', { defaultValue: 'Custom Build' }),
                tagline: t('about.svc_build_tagline', { defaultValue: 'FROM 4 WEEKS' }),
                desc: t('about.svc_build_desc', { defaultValue: 'Discovery → workshop → modules picked → built → deployed on your hardware. Source delivered.' }),
                bullets: [
                  t('about.svc_build_b1', { defaultValue: '4–12 weeks engagement' }),
                  t('about.svc_build_b2', { defaultValue: 'AGPL or commercial license' }),
                  t('about.svc_build_b3', { defaultValue: '30 days post-launch support' }),
                ],
              },
              {
                num: '02',
                icon: Users,
                title: t('about.svc_workshop_title', { defaultValue: 'Workshops' }),
                tagline: t('about.svc_workshop_tagline', { defaultValue: '1–3 DAYS · ON-SITE OR REMOTE' }),
                desc: t('about.svc_workshop_desc', { defaultValue: 'Hands-on sessions: estimating, BIM-to-BOQ, AI takeoff, GAEB pipelines. Recorded for your team library.' }),
                bullets: [
                  t('about.svc_workshop_b1', { defaultValue: 'Up to 12 participants' }),
                  t('about.svc_workshop_b2', { defaultValue: 'Tailored agenda + exercises' }),
                  t('about.svc_workshop_b3', { defaultValue: 'Slides + recordings retained by client' }),
                ],
              },
              {
                num: '03',
                icon: Briefcase,
                title: t('about.svc_consulting_title', { defaultValue: 'Consulting' }),
                tagline: t('about.svc_consulting_tagline', { defaultValue: 'BY THE DAY · OR RETAINER' }),
                desc: t('about.svc_consulting_desc', { defaultValue: 'Standards mapping, cost-DB strategy, pipeline architecture, code review.' }),
                bullets: [
                  t('about.svc_consulting_b1', { defaultValue: 'Async review option' }),
                  t('about.svc_consulting_b2', { defaultValue: 'Outcome document + recommendations' }),
                  t('about.svc_consulting_b3', { defaultValue: 'Rollover into custom build' }),
                ],
              },
            ].map(svc => (
              <div
                key={svc.num}
                className="group relative flex flex-col rounded-2xl border border-border-light bg-surface-secondary/30 p-5 hover:border-oe-blue/40 hover:bg-oe-blue/[0.025] hover:shadow-sm transition-all"
              >
                {/* Numbered badge — Build 01 / Workshops 02 / Consulting 03 */}
                <div className="flex items-center gap-3 mb-3">
                  <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue font-mono text-sm font-bold ring-1 ring-oe-blue/20">
                    {svc.num}
                  </span>
                  <svc.icon size={18} className="text-content-tertiary group-hover:text-oe-blue transition-colors" />
                </div>

                <h3 className="text-base font-bold text-content-primary mb-0.5">{svc.title}</h3>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-oe-blue mb-3">
                  {svc.tagline}
                </p>
                <p className="text-xs text-content-secondary leading-relaxed mb-4">
                  {svc.desc}
                </p>

                <ul className="mt-auto space-y-1.5">
                  {svc.bullets.map((b, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-content-secondary">
                      <ArrowRight size={11} className="mt-1 shrink-0 text-oe-blue" />
                      <span>{b}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          {/* Trusted-by chip list — public client engagements from the site */}
          <div className="mt-6 pt-5 border-t border-border-light">
            <p className="mb-3 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('about.svc_trusted_label', { defaultValue: 'Selected engagements' })}
            </p>
            <div className="flex flex-wrap items-center gap-1.5">
              {[
                'Drees & Sommer',
                'Lindner Group',
                'OTWB',
                'ShapeMaker',
                'Bauindustrie Bayern',
                'TUM',
                'BIM Cluster BW',
                'BIM DAY GENF',
                'Herbert Gruppe',
              ].map(name => (
                <span
                  key={name}
                  className="inline-flex items-center rounded-md border border-border-light bg-surface-primary px-2.5 py-1 text-xs text-content-secondary"
                >
                  {name}
                </span>
              ))}
              <span className="inline-flex items-center rounded-md border border-border-light bg-surface-secondary/40 px-2.5 py-1 text-xs text-content-tertiary italic">
                {t('about.svc_trusted_more', { defaultValue: '+ engagements under NDA' })}
              </span>
            </div>
          </div>

          {/* CTA row — primary contact button (case-studies link removed per
              user request 2026-05-20). */}
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <a href="https://datadrivenconstruction.io/contact-support/" target="_blank" rel="noopener noreferrer">
              <Button variant="primary" size="md" icon={<Mail size={15} />}>
                {t('about.contact_us', { defaultValue: 'Contact Us' })}
              </Button>
            </a>
          </div>
        </div>
      </Card>

      {/* Documentation block — moved down next to License (2-col reference band). */}

      {/* Support the Project — compact 2-col layout so the section doesn't
          stretch endlessly on wide screens. Hero+actions on the left, the
          "Your support enables" backlog list on the right. */}
      <Card
        padding="none"
        className="animate-card-in overflow-hidden"
        style={{ animationDelay: '250ms' }}
      >
        <div className="relative">
          {/* Richer gradient — same vibe, now contained inside a tighter card. */}
          <div className="absolute inset-0 bg-gradient-to-br from-amber-500/[0.10] via-orange-500/[0.06] to-rose-500/[0.10]" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_0%,rgba(251,191,36,0.12),transparent_50%),radial-gradient(circle_at_90%_100%,rgba(244,63,94,0.12),transparent_55%)]" />

          <div className="relative p-6 grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* ── Left column — hero + 3 stacked action cards ── */}
            <div>
              <div className="flex items-center gap-2.5 mb-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-white/70 dark:bg-white/5 shadow-sm ring-1 ring-black/[0.04] dark:ring-white/[0.06]">
                  <Handshake size={18} className="text-oe-blue" />
                </div>
                <h2 className="text-xl font-bold tracking-tight text-content-primary">
                  {t('about.support_title', { defaultValue: 'Support OpenConstructionERP' })}
                </h2>
              </div>
              <p className="text-sm text-content-secondary leading-relaxed mb-5">
                {t('about.support_desc_short', { defaultValue: 'Free, open-source, built by construction professionals. Every star, sponsor, or paid engagement keeps the project alive.' })}
              </p>

              {/* 3 action cards, stacked vertically to keep the section dense */}
              <div className="space-y-2">
                <a
                  href="https://github.com/datadrivenconstruction/OpenConstructionERP"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-center gap-3 rounded-lg border border-border-light bg-surface-primary/80 backdrop-blur-sm px-3.5 py-3 hover:border-amber-400/60 hover:bg-amber-50/60 dark:hover:bg-amber-900/15 transition-colors"
                >
                  <Star size={22} className="shrink-0 text-amber-500 group-hover:scale-110 group-hover:-rotate-6 transition-transform" fill="currentColor" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-bold text-content-primary leading-tight">
                      {t('about.support_star', { defaultValue: 'Star on GitHub' })}
                    </p>
                    <p className="text-2xs text-content-tertiary leading-snug mt-0.5">
                      {t('about.support_star_desc', { defaultValue: 'Show your support — it takes 2 seconds and helps others discover the project' })}
                    </p>
                  </div>
                  <ArrowRight size={14} className="shrink-0 text-content-quaternary group-hover:text-amber-500 group-hover:translate-x-0.5 transition-all" />
                </a>

                <a
                  href="https://github.com/sponsors/datadrivenconstruction"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-center gap-3 rounded-lg border border-border-light bg-surface-primary/80 backdrop-blur-sm px-3.5 py-3 hover:border-rose-400/60 hover:bg-rose-50/60 dark:hover:bg-rose-900/15 transition-colors"
                >
                  <Coffee size={22} className="shrink-0 text-rose-500 group-hover:scale-110 transition-transform" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-bold text-content-primary leading-tight">
                      {t('about.support_sponsor', { defaultValue: 'Become a Sponsor' })}
                    </p>
                    <p className="text-2xs text-content-tertiary leading-snug mt-0.5">
                      {t('about.support_sponsor_desc', { defaultValue: 'Fund new features, regional databases, and keep the project free for everyone' })}
                    </p>
                  </div>
                  <ArrowRight size={14} className="shrink-0 text-content-quaternary group-hover:text-rose-500 group-hover:translate-x-0.5 transition-all" />
                </a>

                <a
                  href="https://datadrivenconstruction.io/contact-support/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-center gap-3 rounded-lg border border-border-light bg-surface-primary/80 backdrop-blur-sm px-3.5 py-3 hover:border-oe-blue/50 hover:bg-oe-blue/[0.06] dark:hover:bg-blue-900/15 transition-colors"
                >
                  <Rocket size={22} className="shrink-0 text-oe-blue group-hover:scale-110 group-hover:-translate-y-0.5 transition-transform" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-bold text-content-primary leading-tight">
                      {t('about.support_consulting', { defaultValue: 'Order Consulting' })}
                    </p>
                    <p className="text-2xs text-content-tertiary leading-snug mt-0.5">
                      {t('about.support_consulting_desc', { defaultValue: 'Need custom features, deployment, or training? We deliver professional solutions worldwide' })}
                    </p>
                  </div>
                  <ArrowRight size={14} className="shrink-0 text-content-quaternary group-hover:text-oe-blue group-hover:translate-x-0.5 transition-all" />
                </a>
              </div>
            </div>
            {/* /Left column */}

            {/* ── Right column — KPI tiles + what your support enables ──
                Two stat tiles on top mirror the visual weight of the left
                column's hero block, so the two halves match height on wide
                screens without leaving a gap below the bullets. ── */}
            <div className="lg:border-l lg:border-border-light/60 dark:lg:border-white/[0.08] lg:pl-6 flex flex-col">
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3 flex items-center gap-1.5">
                <Rocket size={12} className="text-oe-blue" />
                {t('about.support_impact_label', { defaultValue: 'Impact so far' })}
              </p>
              <div className="grid grid-cols-2 gap-2.5 mb-4">
                {[
                  { value: '24', label: t('about.support_kpi_langs', { defaultValue: 'Languages translated' }) },
                  { value: '48', label: t('about.support_kpi_regions', { defaultValue: 'Regional cost packs' }) },
                  { value: '100+', label: t('about.support_kpi_modules', { defaultValue: 'Backend modules' }) },
                  { value: '55K+', label: t('about.support_kpi_cwicr', { defaultValue: 'CWICR positions' }) },
                ].map((kpi, i) => (
                  <div key={i} className="rounded-lg bg-surface-primary/60 backdrop-blur-sm border border-border-light px-3 py-2.5">
                    <div className="text-lg font-bold text-content-primary leading-tight">{kpi.value}</div>
                    <div className="text-2xs text-content-tertiary mt-0.5 leading-snug">{kpi.label}</div>
                  </div>
                ))}
              </div>

              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3 flex items-center gap-1.5">
                <ArrowRight size={12} className="text-oe-blue" />
                {t('about.support_enables', { defaultValue: 'Your support enables:' })}
              </p>
              <ul className="space-y-1.5">
                {[
                  t('about.support_e1', { defaultValue: 'New regional cost databases (CWICR)' }),
                  t('about.support_e2', { defaultValue: 'AI estimation improvements' }),
                  t('about.support_e3', { defaultValue: 'More CAD/BIM format support' }),
                  t('about.support_e4', { defaultValue: 'Better PDF takeoff tools' }),
                  t('about.support_e5', { defaultValue: 'Mobile app development' }),
                  t('about.support_e6', { defaultValue: 'Free workshops and documentation' }),
                ].map((item, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-content-secondary">
                    <ArrowRight size={11} className="mt-1 shrink-0 text-oe-blue" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            {/* /Right column */}
          </div>
        </div>
      </Card>

      {/* Free Guidebook — 5-col internal split: book cover gets 2/5 of the
          width so the cover image can render larger; the 10-part TOC keeps
          3/5 and its tiles read tighter and more uniform. */}
      <Card className="animate-card-in" style={{ animationDelay: '300ms' }}>
        <div className="p-6 grid grid-cols-1 lg:grid-cols-5 gap-6">

          {/* ── Left column — larger book cover + headline + download CTA ── */}
          <div className="lg:col-span-2">
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <BookOpen size={18} className="text-oe-blue" />
              <h2 className="text-lg font-semibold text-content-primary">
                {t('about.book_title', { defaultValue: 'Data-Driven Construction' })}
              </h2>
              <Badge variant="blue" size="sm">Free</Badge>
            </div>
            <p className="text-xs text-content-tertiary mb-4">
              {t('about.book_subtitle', { defaultValue: 'By Artem Boiko · 16 languages · 600+ pages · 10 parts, 173 chapters' })}
            </p>
            <a
              href="https://datadrivenconstruction.io/books/"
              target="_blank"
              rel="noopener noreferrer"
              className="group block overflow-hidden rounded-xl bg-gradient-to-br from-slate-50 via-white to-blue-50 dark:from-slate-900 dark:via-slate-900 dark:to-slate-800 border border-border-light hover:border-oe-blue/40 hover:shadow-lg transition-all max-w-[320px] mx-auto lg:mx-0"
              title={t('about.book_cta', { defaultValue: 'Pick your language on datadrivenconstruction.io' })}
            >
              <img
                src="/brand/ddc-book.png"
                alt={t('about.book_title', { defaultValue: 'Data-Driven Construction' })}
                className="block w-full h-auto transition-transform duration-500 group-hover:scale-[1.02]"
                loading="lazy"
              />
            </a>
            <a
              href="https://datadrivenconstruction.io/books/"
              target="_blank"
              rel="noopener noreferrer"
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors shadow-sm"
            >
              <BookOpen size={16} />
              {t('about.book_download', { defaultValue: 'Download Free' })}
              <ExternalLink size={14} />
            </a>
          </div>
          {/* /Left column */}

          {/* ── Right column — Part-level table of contents (narrower) ── */}
          <div className="lg:col-span-3">
            <p className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
              {t('about.book_toc_label', { defaultValue: 'Inside the book — 10 parts' })}
            </p>
            <ol className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {[
                { num: 'I',    title: t('about.book_p1',  { defaultValue: 'How information has evolved in construction' }) },
                { num: 'II',   title: t('about.book_p2',  { defaultValue: 'How the construction business is drowning in data chaos' }) },
                { num: 'III',  title: t('about.book_p3',  { defaultValue: 'Data framework in construction business processes' }) },
                { num: 'IV',   title: t('about.book_p4',  { defaultValue: 'Data quality: organization, structuring, modeling' }) },
                { num: 'V',    title: t('about.book_p5',  { defaultValue: 'Cost & time calculations: incorporating data into processes' }) },
                { num: 'VI',   title: t('about.book_p6',  { defaultValue: 'CAD & BIM — marketing, reality and the future of design data' }) },
                { num: 'VII',  title: t('about.book_p7',  { defaultValue: 'Data-driven decision-making, analytics and automation' }) },
                { num: 'VIII', title: t('about.book_p8',  { defaultValue: 'Data storage and management in construction' }) },
                { num: 'IX',   title: t('about.book_p9',  { defaultValue: 'Big Data, machine learning and forecasts' }) },
                { num: 'X',    title: t('about.book_p10', { defaultValue: 'The construction industry in the digital age — opportunities & challenges' }) },
              ].map(p => (
                <li key={p.num} className="group flex items-start gap-2.5 rounded-lg border border-border-light bg-surface-secondary/30 px-3 py-2.5 hover:border-oe-blue/30 hover:bg-oe-blue/[0.025] transition-colors">
                  <span className="shrink-0 inline-flex h-6 min-w-[2rem] items-center justify-center rounded-md bg-oe-blue/10 text-oe-blue font-mono text-2xs font-bold ring-1 ring-oe-blue/20 px-1.5">
                    {p.num}
                  </span>
                  <span className="text-xs text-content-secondary leading-snug group-hover:text-content-primary transition-colors">
                    {p.title}
                  </span>
                </li>
              ))}
            </ol>
            <p className="mt-3 text-2xs text-content-tertiary italic">
              {t('about.book_toc_note', { defaultValue: '173 chapters total. Free to read online or download.' })}
            </p>
          </div>
          {/* /Right column */}

        </div>
      </Card>

      {/* Reference band — Documentation + License side-by-side with matched heights. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">

        {/* Documentation — same h-full + flex-col + mt-auto pattern as License so
            both cards land their CTA button on the same baseline. The body is
            enriched with a "Popular topics" 2x3 mini-grid to fill the column
            instead of leaving whitespace below the 4 high-level bullets. */}
        <Card className="animate-card-in h-full flex flex-col" style={{ animationDelay: '240ms' }}>
          <div className="p-6 flex flex-col flex-1">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle">
                <BookOpen size={20} className="text-oe-blue" />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-semibold text-content-primary">
                  {t('about.docs_title', { defaultValue: 'Documentation' })}
                </h2>
                <p className="text-xs text-content-tertiary">
                  {t('about.docs_desc', { defaultValue: 'Installation guides, feature overview, API reference, and tutorials' })}
                </p>
              </div>
            </div>
            <ul className="space-y-1.5 text-xs text-content-secondary mb-4">
              {[
                t('about.docs_b1', { defaultValue: 'Installation & deployment guides (Docker, VPS, Kubernetes)' }),
                t('about.docs_b2', { defaultValue: 'Feature walkthroughs — BOQ editor, BIM viewer, takeoff' }),
                t('about.docs_b3', { defaultValue: 'OpenAPI reference for all 100+ backend modules' }),
                t('about.docs_b4', { defaultValue: 'Module SDK — write your own plugin' }),
              ].map((b, i) => (
                <li key={i} className="flex items-start gap-2">
                  <ArrowRight size={11} className="mt-1 shrink-0 text-oe-blue" />
                  <span>{b}</span>
                </li>
              ))}
            </ul>

            {/* ── Popular topics — direct deep-links so users jump straight into
                the doc page they need, instead of landing on the index. ── */}
            <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('about.docs_popular_label', { defaultValue: 'Popular topics' })}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {[
                { href: 'https://openconstructionerp.com/docs.html#quickstart', label: t('about.docs_pop_quickstart', { defaultValue: 'Quick start — Docker compose' }) },
                { href: 'https://openconstructionerp.com/docs.html#bim-import', label: t('about.docs_pop_bim', { defaultValue: 'Import BIM (RVT/IFC) → BOQ' }) },
                { href: 'https://openconstructionerp.com/docs.html#gaeb', label: t('about.docs_pop_gaeb', { defaultValue: 'GAEB X83/X84 import & export' }) },
                { href: 'https://openconstructionerp.com/docs.html#takeoff', label: t('about.docs_pop_takeoff', { defaultValue: 'PDF takeoff with annotations' }) },
                { href: 'https://openconstructionerp.com/docs.html#module-sdk', label: t('about.docs_pop_sdk', { defaultValue: 'Module SDK · write a plugin' }) },
                { href: 'https://openconstructionerp.com/docs.html#deploy', label: t('about.docs_pop_deploy', { defaultValue: 'VPS deployment guide' }) },
              ].map(topic => (
                <a
                  key={topic.href}
                  href={topic.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2 hover:border-oe-blue/40 hover:bg-oe-blue/[0.04] transition-all"
                >
                  <span className="text-2xs text-content-secondary group-hover:text-content-primary leading-snug">
                    {topic.label}
                  </span>
                  <ArrowRight size={11} className="shrink-0 text-content-quaternary group-hover:text-oe-blue group-hover:translate-x-0.5 transition-all" />
                </a>
              ))}
            </div>

            <div className="mt-auto pt-4">
              <a href="https://openconstructionerp.com/docs.html" target="_blank" rel="noopener noreferrer">
                <Button variant="primary" size="md" icon={<BookOpen size={15} />}>
                  {t('about.docs_open', { defaultValue: 'Open Docs' })}
                </Button>
              </a>
            </div>
          </div>
        </Card>

        {/* License — restructured into "You can / You must" so users see the
            AGPL trade-off at a glance instead of reading prose. CTA at bottom
            matches the Documentation card's "Open Docs" button position. */}
        <Card className="animate-card-in h-full flex flex-col" style={{ animationDelay: '260ms' }}>
          <div className="p-6 flex flex-col flex-1">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 dark:bg-emerald-900/20">
                <Shield size={20} className="text-emerald-500" />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-semibold text-content-primary">
                  {t('about.license_title', { defaultValue: 'License & Open Source' })}
                </h2>
                <p className="text-xs text-content-tertiary">
                  {t('about.license_subtitle', { defaultValue: 'AGPL-3.0 — free for any use, including commercial' })}
                </p>
              </div>
            </div>
            <p className="text-sm text-content-secondary leading-relaxed mb-4">
              {t('about.license_desc_short', { defaultValue: 'GNU Affero General Public License v3.0 — copyleft. The full text ships with the source and is also available at gnu.org/licenses/agpl-3.0.' })}
            </p>

            {/* ── You can / You must — concrete bullet pairs so the AGPL
                obligations are visible before download, not after lawyers. ── */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3 mb-4">
              <div>
                <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                  {t('about.license_youcan_label', { defaultValue: 'You can' })}
                </p>
                <ul className="space-y-1 text-xs text-content-secondary leading-snug">
                  {[
                    t('about.license_youcan_1', { defaultValue: 'Use for any purpose, including commercial' }),
                    t('about.license_youcan_2', { defaultValue: 'Self-host on your own hardware' }),
                    t('about.license_youcan_3', { defaultValue: 'Modify, fork, and redistribute' }),
                    t('about.license_youcan_4', { defaultValue: 'Build proprietary modules on top' }),
                  ].map((b, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <span className="mt-1 inline-block h-1 w-1 rounded-full bg-emerald-500 shrink-0" />
                      <span>{b}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-amber-600 dark:text-amber-400">
                  {t('about.license_youmust_label', { defaultValue: 'You must' })}
                </p>
                <ul className="space-y-1 text-xs text-content-secondary leading-snug">
                  {[
                    t('about.license_youmust_1', { defaultValue: 'Share modifications under AGPL-3.0' }),
                    t('about.license_youmust_2', { defaultValue: 'Provide source to network users' }),
                    t('about.license_youmust_3', { defaultValue: 'Keep copyright + license notices' }),
                    t('about.license_youmust_4', { defaultValue: 'Document what you changed' }),
                  ].map((b, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <span className="mt-1 inline-block h-1 w-1 rounded-full bg-amber-500 shrink-0" />
                      <span>{b}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="flex flex-wrap gap-1.5 mb-4">
              <Badge variant="success" size="sm">{t('about.license_badge_free', { defaultValue: 'Free to use' })}</Badge>
              <Badge variant="success" size="sm">{t('about.license_badge_oss', { defaultValue: 'Open source' })}</Badge>
              <Badge variant="success" size="sm">{t('about.license_badge_selfhost', { defaultValue: 'Self-hosted' })}</Badge>
              <Badge variant="success" size="sm">{t('about.license_badge_nolockin', { defaultValue: 'No vendor lock-in' })}</Badge>
              <Badge variant="blue" size="sm">AGPL-3.0</Badge>
            </div>

            <div className="mt-auto pt-3 border-t border-border-light">
              <p className="text-xs text-content-secondary mb-2">
                {t('about.license_commercial_short', { defaultValue: 'Need a commercial licence (without AGPL obligations) or an enterprise SLA?' })}
              </p>
              <a href="https://datadrivenconstruction.io/contact-support/" target="_blank" rel="noopener noreferrer">
                <Button variant="secondary" size="md" icon={<Shield size={15} />}>
                  {t('about.license_commercial_cta', { defaultValue: 'Commercial licensing' })}
                </Button>
              </a>
            </div>
          </div>
        </Card>

      </div>

      {/* Changelog — anchored so the header's "View all" jump target lands
          on the section heading instead of mid-scroll. */}
      <Card>
        <div className="p-6" data-changelog-anchor>
          <Changelog />
        </div>
      </Card>

      {/* Credits */}
      <div className="text-center py-4 text-xs text-content-quaternary">
        <p className="flex items-center justify-center gap-1">
          {t('about.built_by', { defaultValue: 'Created by Artem Boiko' })}
          {' · '}
          <a href="https://datadrivenconstruction.io" target="_blank" rel="noopener noreferrer" className="hover:text-oe-blue transition-colors">
            datadrivenconstruction.io
          </a>
        </p>
        <p className="mt-1">&copy; 2026 Data Driven Construction. All rights reserved.</p>
      </div>
    </div>
  );
}
