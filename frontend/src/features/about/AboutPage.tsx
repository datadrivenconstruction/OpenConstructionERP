/**
 * AboutPage — Application info, author, license, consulting services.
 */

import { useTranslation } from 'react-i18next';
import {
  Mail, Shield, BookOpen, Users, Award,
  Code2, Building2, Briefcase, Globe, ExternalLink,
  Linkedin, Youtube, Star, Coffee, Rocket, ArrowRight, Handshake,
} from 'lucide-react';
import { Card, Button, Badge } from '@/shared/ui';
import { Changelog } from './Changelog';

export function AboutPage() {
  const { t } = useTranslation();

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="text-center py-6">
        <div className="inline-flex items-center gap-2 mb-4">
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
          </span>
          <span className="text-xs font-semibold uppercase tracking-widest text-emerald-600">Open Source</span>
        </div>
        <h1 className="text-3xl font-bold text-content-primary tracking-tight">OpenConstructionERP</h1>
        <p className="mt-2 text-base text-content-secondary">
          {t('about.tagline', { defaultValue: 'The #1 open-source platform for construction cost estimation' })}
        </p>
        <div className="mt-3 flex items-center justify-center gap-3 text-sm text-content-tertiary">
          <span>v0.1.1</span>
          <span>&middot;</span>
          <span>2026</span>
          <span>&middot;</span>
          <Badge variant="blue" size="sm">AGPL-3.0</Badge>
        </div>
      </div>

      {/* Platform Stats — first, so user sees what the platform offers */}
      <Card className="animate-card-in" style={{ animationDelay: '50ms' }}>
        <div className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <Award size={18} className="text-amber-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('about.platform_title', { defaultValue: 'Platform Capabilities' })}
            </h2>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { value: '55K+', label: t('about.stat_costs', { defaultValue: 'Cost Items (CWICR)' }) },
              { value: '20+', label: t('about.stat_langs', { defaultValue: 'Languages' }) },
              { value: '11', label: t('about.stat_regions', { defaultValue: 'Regional Databases' }) },
              { value: '42', label: t('about.stat_rules', { defaultValue: 'Validation Rules' }) },
            ].map((s, i) => (
              <div key={i} className="text-center rounded-xl bg-surface-secondary/50 p-4">
                <div className="text-2xl font-bold text-content-primary">{s.value}</div>
                <div className="text-xs text-content-tertiary mt-1">{s.label}</div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-sm text-content-secondary leading-relaxed">
            {t('about.platform_desc', { defaultValue: 'OpenConstructionERP covers the full construction estimation workflow — BOQ editing, 4D scheduling, 5D cost modeling, AI-powered estimation, CAD/BIM quantity takeoff (RVT, IFC, DWG, DGN), tendering, and reporting. Supports DIN 276, NRM 1/2, MasterFormat, GAEB, and custom standards.' })}
          </p>
        </div>
      </Card>

      {/* Data Driven Construction */}
      <Card className="animate-card-in" style={{ animationDelay: '100ms' }}>
        <div className="p-6">
          {/* DDC Logo + Header */}
          <div className="flex items-center gap-3 mb-4">
            <a href="https://datadrivenconstruction.io" target="_blank" rel="noopener noreferrer" className="shrink-0">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white font-extrabold text-lg shadow-md hover:shadow-lg transition-shadow">
                DDC
              </div>
            </a>
            <div>
              <a href="https://datadrivenconstruction.io" target="_blank" rel="noopener noreferrer" className="hover:text-oe-blue transition-colors">
                <h2 className="text-lg font-semibold text-content-primary flex items-center gap-1.5">
                  Data Driven Construction
                  <ExternalLink size={13} className="text-content-quaternary" />
                </h2>
              </a>
              <p className="text-xs text-content-tertiary">datadrivenconstruction.io</p>
            </div>
          </div>

          <p className="text-sm text-content-secondary leading-relaxed mb-4">
            {t('about.ddc_desc', { defaultValue: 'The company behind OpenConstructionERP. Data Driven Construction develops open-source tools and commercial solutions for the global construction industry. Our mission: make professional cost estimation accessible, transparent, and AI-augmented — from a solo quantity surveyor to enterprise-scale contractors.' })}
          </p>

          {/* Product cards with links */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <a href="https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR" target="_blank" rel="noopener noreferrer" className="rounded-xl border border-border-light bg-surface-secondary/30 p-4 text-center hover:border-oe-blue/40 hover:bg-oe-blue/[0.03] transition-all group">
              <div className="text-2xl font-bold text-content-primary group-hover:text-oe-blue transition-colors">CWICR</div>
              <div className="text-xs text-content-tertiary mt-1">
                {t('about.ddc_cwicr', { defaultValue: '55,000+ cost items · 9 languages · 11 regional databases' })}
              </div>
              <div className="mt-2 text-2xs text-oe-blue opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-1">
                <ExternalLink size={10} /> GitHub
              </div>
            </a>
            <a href="https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto" target="_blank" rel="noopener noreferrer" className="rounded-xl border border-border-light bg-surface-secondary/30 p-4 text-center hover:border-oe-blue/40 hover:bg-oe-blue/[0.03] transition-all group">
              <div className="text-2xl font-bold text-content-primary group-hover:text-oe-blue transition-colors">cad2data</div>
              <div className="text-xs text-content-tertiary mt-1">
                {t('about.ddc_cad2data', { defaultValue: 'CAD/BIM pipeline — RVT, IFC, DWG, DGN to structured quantities' })}
              </div>
              <div className="mt-2 text-2xs text-oe-blue opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-1">
                <ExternalLink size={10} /> GitHub
              </div>
            </a>
            <a href="https://datadrivenconstruction.io/contact-support/" target="_blank" rel="noopener noreferrer" className="rounded-xl border border-border-light bg-surface-secondary/30 p-4 text-center hover:border-oe-blue/40 hover:bg-oe-blue/[0.03] transition-all group">
              <div className="text-2xl font-bold text-content-primary group-hover:text-oe-blue transition-colors">DDC</div>
              <div className="text-xs text-content-tertiary mt-1">
                {t('about.ddc_platform', { defaultValue: 'Consulting, training & enterprise solutions for digital construction' })}
              </div>
              <div className="mt-2 text-2xs text-oe-blue opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-1">
                <ExternalLink size={10} /> Contact
              </div>
            </a>
          </div>
        </div>
      </Card>

      {/* Founder & Creator */}
      <Card className="animate-card-in" style={{ animationDelay: '150ms' }}>
        <div className="p-6">
          <div className="flex items-start gap-5">
            <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-oe-blue to-blue-600 text-2xl font-bold text-white shadow-lg">
              AB
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-bold text-content-primary">
                {t('about.founder_name', { defaultValue: 'Artem Boiko' })}
              </h2>
              <p className="text-sm text-oe-blue font-medium">
                {t('about.founder_role', { defaultValue: 'Consultant for Automation & Data in Construction' })}
              </p>
              <p className="mt-3 text-sm text-content-secondary leading-relaxed">
                {t('about.founder_bio', { defaultValue: 'Consultant specializing in automation, data engineering, and AI for the construction industry. Author of open-source tools — CWICR (construction cost database, 55,000+ items, 11 regional databases, 9 languages), cad2data (CAD/BIM data extraction pipeline for RVT, IFC, DWG, DGN), and DDC Community Toolkit. Creator of OpenConstructionERP. Founder of Data Driven Construction — bringing modern technology, AI, and open data standards to the global construction industry.' })}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Badge variant="blue" size="sm">Automation & Data</Badge>
                <Badge variant="blue" size="sm">CWICR & cad2data author</Badge>
                <Badge variant="blue" size="sm">AI & construction</Badge>
                <Badge variant="blue" size="sm">Open-source advocate</Badge>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <a
                  href="https://www.linkedin.com/in/boikoartem/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[#0A66C2] px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-[#004182] transition-colors"
                >
                  <Linkedin size={14} />
                  LinkedIn
                </a>
                <a
                  href="https://www.youtube.com/@datadrivenconstruction"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[#FF0000] px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-[#CC0000] transition-colors"
                >
                  <Youtube size={14} />
                  YouTube
                </a>
                <a
                  href="https://datadrivenconstruction.io"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3.5 py-2 text-sm font-medium text-content-primary hover:bg-surface-secondary transition-colors"
                >
                  <Globe size={14} />
                  Website
                </a>
                <a
                  href="https://github.com/datadrivenconstruction"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3.5 py-2 text-sm font-medium text-content-primary hover:bg-surface-secondary transition-colors"
                >
                  <Code2 size={14} />
                  GitHub
                </a>
              </div>
            </div>
          </div>
        </div>
      </Card>

      {/* Consulting Services */}
      <Card>
        <div className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <Briefcase size={18} className="text-oe-blue" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('about.services_title', { defaultValue: 'Consulting & Professional Services' })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary leading-relaxed mb-4">
            {t('about.services_desc', { defaultValue: 'Data Driven Construction offers professional consulting services for construction companies, cost estimators, and technology teams worldwide.' })}
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[
              { icon: Building2, title: t('about.service_estimation', { defaultValue: 'Cost Estimation Consulting' }), desc: t('about.service_estimation_desc', { defaultValue: 'Expert BOQ preparation, cost analysis, and estimation methodology for projects of any scale.' }) },
              { icon: Code2, title: t('about.service_implementation', { defaultValue: 'Platform Implementation' }), desc: t('about.service_implementation_desc', { defaultValue: 'Custom deployment, integration with existing systems (SAP, Procore, MS Project), and team training.' }) },
              { icon: BookOpen, title: t('about.service_databases', { defaultValue: 'Cost Database Development' }), desc: t('about.service_databases_desc', { defaultValue: 'Regional cost database creation, CWICR licensing, and data pipeline setup for your organization.' }) },
              { icon: Users, title: t('about.service_training', { defaultValue: 'Training & Workshops' }), desc: t('about.service_training_desc', { defaultValue: 'Team training on digital estimation, AI-powered workflows, and BIM quantity takeoff.' }) },
            ].map((s, i) => (
              <div key={i} className="rounded-xl border border-border-light p-4 hover:bg-surface-secondary/30 transition-colors">
                <div className="flex items-center gap-2 mb-2">
                  <s.icon size={16} className="text-oe-blue" />
                  <span className="text-sm font-semibold text-content-primary">{s.title}</span>
                </div>
                <p className="text-xs text-content-tertiary leading-relaxed">{s.desc}</p>
              </div>
            ))}
          </div>

          <div className="mt-4 flex items-center gap-3">
            <a href="https://datadrivenconstruction.io/contact-support/" target="_blank" rel="noopener noreferrer">
              <Button variant="primary" size="sm" icon={<Mail size={14} />}>
                {t('about.contact_us', { defaultValue: 'Contact Us' })}
              </Button>
            </a>
            <span className="text-xs text-content-tertiary">
              {t('about.contact_hint', { defaultValue: 'Available worldwide' })}
            </span>
          </div>
        </div>
      </Card>

      {/* Support the Project */}
      <Card className="animate-card-in overflow-hidden" style={{ animationDelay: '250ms' }}>
        <div className="relative">
          {/* Gradient background */}
          <div className="absolute inset-0 bg-gradient-to-br from-amber-500/[0.06] via-orange-500/[0.04] to-rose-500/[0.06]" />

          <div className="relative p-6">
            {/* Big heading */}
            <div className="text-center mb-5">
              <div className="inline-flex items-center gap-2 mb-3">
                <Handshake size={22} className="text-oe-blue" />
                <h2 className="text-xl font-bold text-content-primary">
                  {t('about.support_title', { defaultValue: 'Support OpenConstructionERP' })}
                </h2>
              </div>
              <p className="text-sm text-content-secondary leading-relaxed max-w-xl mx-auto">
                {t('about.support_desc', { defaultValue: 'This project is free and open-source — built by construction professionals, for construction professionals. Your support keeps it alive and growing. Every star, share, and contribution helps us build better tools for the industry.' })}
              </p>
            </div>

            {/* Support options grid */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
              {/* Star on GitHub */}
              <a
                href="https://github.com/datadrivenconstruction/OpenConstructionERP"
                target="_blank"
                rel="noopener noreferrer"
                className="flex flex-col items-center gap-2 rounded-xl border border-amber-200/60 dark:border-amber-800/30 bg-amber-50/50 dark:bg-amber-900/10 p-5 hover:border-amber-400 hover:shadow-md transition-all group"
              >
                <Star size={28} className="text-amber-500 group-hover:scale-110 transition-transform" />
                <span className="text-sm font-bold text-content-primary">
                  {t('about.support_star', { defaultValue: 'Star on GitHub' })}
                </span>
                <span className="text-2xs text-content-tertiary text-center">
                  {t('about.support_star_desc', { defaultValue: 'Show your support — it takes 2 seconds and helps others discover the project' })}
                </span>
              </a>

              {/* Buy a Coffee / Sponsor */}
              <a
                href="https://github.com/sponsors/datadrivenconstruction"
                target="_blank"
                rel="noopener noreferrer"
                className="flex flex-col items-center gap-2 rounded-xl border border-rose-200/60 dark:border-rose-800/30 bg-rose-50/50 dark:bg-rose-900/10 p-5 hover:border-rose-400 hover:shadow-md transition-all group"
              >
                <Coffee size={28} className="text-rose-500 group-hover:scale-110 transition-transform" />
                <span className="text-sm font-bold text-content-primary">
                  {t('about.support_sponsor', { defaultValue: 'Become a Sponsor' })}
                </span>
                <span className="text-2xs text-content-tertiary text-center">
                  {t('about.support_sponsor_desc', { defaultValue: 'Fund new features, regional databases, and keep the project free for everyone' })}
                </span>
              </a>

              {/* Consulting */}
              <a
                href="https://datadrivenconstruction.io/contact-support/"
                target="_blank"
                rel="noopener noreferrer"
                className="flex flex-col items-center gap-2 rounded-xl border border-oe-blue/20 dark:border-blue-800/30 bg-oe-blue/[0.04] dark:bg-blue-900/10 p-5 hover:border-oe-blue hover:shadow-md transition-all group"
              >
                <Rocket size={28} className="text-oe-blue group-hover:scale-110 transition-transform" />
                <span className="text-sm font-bold text-content-primary">
                  {t('about.support_consulting', { defaultValue: 'Order Consulting' })}
                </span>
                <span className="text-2xs text-content-tertiary text-center">
                  {t('about.support_consulting_desc', { defaultValue: 'Need custom features, deployment, or training? We deliver professional solutions worldwide' })}
                </span>
              </a>
            </div>

            {/* What your support enables */}
            <div className="rounded-xl bg-surface-secondary/50 border border-border-light/40 p-4">
              <p className="text-xs font-semibold text-content-primary mb-2 flex items-center gap-1.5">
                <Rocket size={13} className="text-oe-blue" />
                {t('about.support_enables', { defaultValue: 'Your support enables:' })}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                {[
                  t('about.support_e1', { defaultValue: 'New regional cost databases (CWICR)' }),
                  t('about.support_e2', { defaultValue: 'AI estimation improvements' }),
                  t('about.support_e3', { defaultValue: 'More CAD/BIM format support' }),
                  t('about.support_e4', { defaultValue: 'Better PDF takeoff tools' }),
                  t('about.support_e5', { defaultValue: 'Mobile app development' }),
                  t('about.support_e6', { defaultValue: 'Free workshops and documentation' }),
                ].map((item, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-xs text-content-secondary">
                    <ArrowRight size={10} className="text-oe-blue shrink-0" />
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </Card>

      {/* License */}
      <Card>
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Shield size={18} className="text-emerald-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('about.license_title', { defaultValue: 'License & Open Source' })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary leading-relaxed mb-3">
            {t('about.license_desc', { defaultValue: 'OpenConstructionERP is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). This means you can freely use, modify, and distribute the software, as long as any modifications are also made available under the same license.' })}
          </p>
          <div className="flex flex-wrap gap-2">
            <Badge variant="success" size="sm">Free to use</Badge>
            <Badge variant="success" size="sm">Open source</Badge>
            <Badge variant="success" size="sm">Self-hosted</Badge>
            <Badge variant="success" size="sm">No vendor lock-in</Badge>
            <Badge variant="blue" size="sm">AGPL-3.0</Badge>
          </div>
          <p className="text-xs text-content-quaternary mt-3">
            {t('about.license_commercial', { defaultValue: 'For commercial licensing (proprietary use without AGPL obligations), enterprise support, or SLA agreements, please contact us.' })}
          </p>
        </div>
      </Card>

      {/* Changelog */}
      <Card>
        <div className="p-6">
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
