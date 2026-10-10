// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Geo Hub admin page (``/geo/admin``).
 *
 * Hosts the geocode cache admin panel today; reserved for future
 * admin-only Geo Hub surfaces (per-tenant base imagery defaults,
 * terrain source enrollment, etc.). Admin gating is enforced both by
 * ``<AdminOnly>`` on the route and by backend RBAC (``geo_hub.admin``)
 * on every API call.
 */

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

import { AdminOnly } from '@/shared/auth/AdminOnly';
import { Breadcrumb, Button } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';

import { GeocodeCacheAdminPanel } from './GeocodeCacheAdminPanel';
import { GeocodingConsentPanel } from './GeocodingConsent';

export function GeoHubAdminPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <AdminOnly redirectTo="/404">
      <div className="space-y-5 animate-fade-in">
        <Breadcrumb
          items={[
            { label: t('sidebar.geo_hub', { defaultValue: 'Geo Hub' }), to: '/geo' },
            { label: t('geo_hub.admin_title', { defaultValue: 'Geo Hub Admin' }) },
          ]}
        />
        <PageHeader
          srTitle={t('geo_hub.admin_title', { defaultValue: 'Geo Hub Admin' })}
          subtitle={t('geo_hub.admin_subtitle', {
            defaultValue: 'Operator-only utilities',
          })}
          actions={
            <Button
              variant="ghost"
              size="sm"
              icon={<ArrowLeft size={14} strokeWidth={2} />}
              onClick={() => navigate('/geo')}
            >
              {t('common.back', { defaultValue: 'Back' })}
            </Button>
          }
        />
        <GeocodingConsentPanel />
        <GeocodeCacheAdminPanel />
      </div>
    </AdminOnly>
  );
}

export default GeoHubAdminPage;
