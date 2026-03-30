/**
 * AboutPage — Application info, author, license, consulting services.
 */

import { useTranslation } from 'react-i18next';
import {
  Mail, Shield, BookOpen, Users, Award,
  Code2, Building2, Briefcase, Globe, ExternalLink,
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
          <span>v0.1.0</span>
          <span>&middot;</span>
          <span>2026</span>
          <span>&middot;</span>
          <Badge variant="blue" size="sm">AGPL-3.0</Badge>
        </div>
      </div>

      {/* Founder & Creator */}
      <Card className="animate-card-in" style={{ animationDelay: '50ms' }}>
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
                {t('about.founder_role', { defaultValue: 'Creator & Lead Developer' })}
              </p>
              <p className="mt-3 text-sm text-content-secondary leading-relaxed">
                {t('about.founder_bio', { defaultValue: 'Data expert in the construction industry. Author of open-source tools — CWICR (construction cost database, 55,000+ items, 9 languages), cad2db (CAD/BIM to structured data pipeline), and various open workflows and data pipelines for construction estimation. Founder of Data Driven Construction — bringing modern technology, AI, and open data standards to the global construction industry.' })}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Badge variant="blue" size="sm">Construction data expert</Badge>
                <Badge variant="blue" size="sm">CWICR & cad2db author</Badge>
                <Badge variant="blue" size="sm">Open-source workflows</Badge>
                <Badge variant="blue" size="sm">AI-first estimation</Badge>
              </div>
              <div className="mt-4 flex items-center gap-3">
                <a
                  href="https://datadrivenconstruction.io"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-oe-blue/90 transition-colors"
                >
                  <Globe size={14} />
                  datadrivenconstruction.io
                  <ExternalLink size={12} />
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

      {/* Data Driven Construction */}
      <Card className="animate-card-in" style={{ animationDelay: '100ms' }}>
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Globe size={18} className="text-oe-blue" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('about.ddc_title', { defaultValue: 'Data Driven Construction' })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary leading-relaxed mb-4">
            {t('about.ddc_desc', { defaultValue: 'The company behind OpenConstructionERP. Data Driven Construction develops open-source tools and commercial solutions for the global construction industry. Our mission: make professional cost estimation accessible, transparent, and AI-augmented — from a solo quantity surveyor to enterprise-scale contractors.' })}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-xl border border-border-light bg-surface-secondary/30 p-4 text-center">
              <div className="text-2xl font-bold text-content-primary">CWICR</div>
              <div className="text-xs text-content-tertiary mt-1">
                {t('about.ddc_cwicr', { defaultValue: '55,000+ cost items across 9 languages and 11 regional price databases' })}
              </div>
            </div>
            <div className="rounded-xl border border-border-light bg-surface-secondary/30 p-4 text-center">
              <div className="text-2xl font-bold text-content-primary">cad2db</div>
              <div className="text-xs text-content-tertiary mt-1">
                {t('about.ddc_cad2db', { defaultValue: 'CAD/BIM to database pipeline — DWG, RVT, IFC to structured quantities' })}
              </div>
            </div>
            <div className="rounded-xl border border-border-light bg-surface-secondary/30 p-4 text-center">
              <div className="text-2xl font-bold text-content-primary">DDC</div>
              <div className="text-xs text-content-tertiary mt-1">
                {t('about.ddc_platform', { defaultValue: 'Consulting, training, and enterprise solutions for digital construction' })}
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
            <a href="https://OpenConstructionERP.com" target="_blank" rel="noopener noreferrer">
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

      {/* Platform Stats */}
      <Card>
        <div className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <Award size={18} className="text-amber-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('about.platform_title', { defaultValue: 'Platform Capabilities' })}
            </h2>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { value: '55K+', label: t('about.stat_costs', { defaultValue: 'Cost Items' }) },
              { value: '21', label: t('about.stat_langs', { defaultValue: 'Languages' }) },
              { value: '20', label: t('about.stat_regions', { defaultValue: 'Regional Standards' }) },
              { value: '42', label: t('about.stat_rules', { defaultValue: 'Validation Rules' }) },
            ].map((s, i) => (
              <div key={i} className="text-center rounded-xl bg-surface-secondary/50 p-4">
                <div className="text-2xl font-bold text-content-primary">{s.value}</div>
                <div className="text-xs text-content-tertiary mt-1">{s.label}</div>
              </div>
            ))}
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
