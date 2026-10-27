// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The sign-in pages in the Classic interface style: a calm side panel with
 * plain facts and a footer with version, links and the operator. Both render
 * on every look but are shown by CSS only under html[data-look="classic"]
 * (index.css, "Classic auth"), where the decorative standard panel is hidden.
 */
import { useTranslation } from 'react-i18next';
import { APP_VERSION } from '@/shared/lib/version';
import { useBrandingStore } from '@/stores/useBrandingStore';

export function ClassicAuthAside() {
  const { t } = useTranslation();
  return (
    <aside className="oe-auth-classic-only oe-auth-aside" aria-hidden={false}>
      <div className="oe-auth-aside-inner">
        <h1 className="text-[22px] font-semibold leading-tight text-content-primary">
          {t('auth_classic.headline', { defaultValue: 'Estimating and project control for construction' })}
        </h1>
        <p className="mt-3 text-sm text-content-secondary">
          {t('auth_classic.facts', { defaultValue: 'Open source, self-hosted. GAEB, DIN 276, NRM and MasterFormat built in.' })}
        </p>
        <ul className="mt-6 space-y-2 text-sm text-content-secondary">
          <li>{t('auth_classic.point_estimate', { defaultValue: 'Bills of quantities, cost databases and tenders' })}</li>
          <li>{t('auth_classic.point_control', { defaultValue: 'Schedules, budgets, changes and payments' })}</li>
          <li>{t('auth_classic.point_data', { defaultValue: 'Your data stays on your server and exports in open formats' })}</li>
        </ul>
      </div>
    </aside>
  );
}

export function ClassicAuthFooter() {
  const { t } = useTranslation();
  const operator = useBrandingStore((s) => s.companyName);
  return (
    <footer className="oe-auth-classic-only oe-auth-footer">
      <span className="tabular-nums">v{APP_VERSION}</span>
      <span aria-hidden>·</span>
      <a href="https://openconstructionerp.com/docs" target="_blank" rel="noopener noreferrer">
        {t('auth_classic.docs', { defaultValue: 'Docs' })}
      </a>
      <span aria-hidden>·</span>
      <a href="/api/health" target="_blank" rel="noopener noreferrer">
        {t('auth_classic.status', { defaultValue: 'Status' })}
      </a>
      <span aria-hidden>·</span>
      <a href="https://openconstructionerp.com/privacy" target="_blank" rel="noopener noreferrer">
        {t('auth_classic.privacy', { defaultValue: 'Privacy' })}
      </a>
      {operator && (
        <>
          <span aria-hidden>·</span>
          <span>{operator}</span>
        </>
      )}
    </footer>
  );
}
