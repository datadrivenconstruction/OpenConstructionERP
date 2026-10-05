// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The builder's own logo (or company name) at the top of the client portal,
// so a homeowner opening a sign-in link sees who sent it. The brand comes
// from the same workspace setting the staff sidebar and the login page use:
// GET /api/v1/branding/ is public, so it loads before the client signs in.
// With no custom brand set the header renders nothing.

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useBrandingStore } from '@/stores/useBrandingStore';

export function PortalBrandHeader() {
  const { t } = useTranslation();
  const mode = useBrandingStore((s) => s.mode);
  const logoDataUrl = useBrandingStore((s) => s.logoDataUrl);
  const companyName = useBrandingStore((s) => s.companyName.trim());

  useEffect(() => {
    void useBrandingStore.getState().hydrateFromServer();
  }, []);

  const showLogo = mode === 'logo' && !!logoDataUrl;
  const showName = mode === 'text' && !!companyName;
  if (!showLogo && !showName) return null;

  return (
    <header className="mb-6 flex flex-col items-center" data-testid="portal-brand-header">
      {showLogo ? (
        <img
          src={logoDataUrl ?? undefined}
          alt={companyName || t('portal.brand_logo_alt', { defaultValue: 'Company logo' })}
          className="block max-h-14 w-auto max-w-full object-contain"
          draggable={false}
        />
      ) : (
        <span
          className="block max-w-full truncate text-center text-2xl font-extrabold leading-none text-content-primary"
          title={companyName}
        >
          {companyName}
        </span>
      )}
      {/* Subordinate attribution stays visible (AGPL-3.0), as on the login page. */}
      <span className="mt-2 block text-[11px] leading-none text-content-tertiary">
        by{' '}
        <span className="font-semibold tracking-tight">
          Open<span className="text-oe-blue/80">Construction</span>
          <span className="text-content-quaternary">ERP</span>
        </span>
      </span>
    </header>
  );
}
