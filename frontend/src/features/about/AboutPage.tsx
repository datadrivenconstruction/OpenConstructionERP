/**
 * AboutPage — Application info, author, license, consulting services.
 */

import { useTranslation } from 'react-i18next';
import {
  Mail, Shield, BookOpen, Users, Award,
  Code2, Building2, Briefcase,
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
              {t('about.contact_hint', { defaultValue: 'Available worldwide in English, German, and Russian' })}
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
              { value: '20', label: t('about.stat_langs', { defaultValue: 'Languages' }) },
              { value: '11', label: t('about.stat_regions', { defaultValue: 'Regional DBs' }) },
              { value: '18', label: t('about.stat_rules', { defaultValue: 'Validation Rules' }) },
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
          {t('about.built_by', { defaultValue: 'Created by Artem Boiko · Data Driven Construction' })}
        </p>
        <p className="mt-1">&copy; 2026 Data Driven Construction. All rights reserved.</p>
      </div>
    </div>
  );
}
