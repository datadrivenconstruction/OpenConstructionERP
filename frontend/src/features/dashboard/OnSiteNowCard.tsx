// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * OnSiteNowCard - dashboard widget for the geofenced time clock​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: how many
 * people are clocked in right now, taps waiting for a supervisor, and shifts
 * with no clock-out. Self-hides when there is no project or the clock is off.
 */

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useClockSettings, useClockStatus } from '@/features/field-time/clockApi';
import { KpiStrip } from './KpiStrip';

export function OnSiteNowCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  const settingsQ = useClockSettings(projectId);
  const enabled = settingsQ.data?.enabled === true;
  const statusQ = useClockStatus(enabled ? projectId : '');
  const data = statusQ.data;

  if (!projectId || !enabled || !data) return null;

  return (
    <Card className="h-full">
      <CardHeader
        title={t('field_clock.widget_title', { defaultValue: 'On site now' })}
        subtitle={t('field_clock.widget_subtitle', {
          defaultValue_one: '{{count}} person clocked in',
          defaultValue_other: '{{count}} people clocked in',
          count: data.on_site_count,
        })}
        action={
          <button
            type="button"
            onClick={() => navigate(`/projects/${projectId}/field-time?tab=approvals`)}
            className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            {t('field_clock.widget_open', { defaultValue: 'Open approvals' })}
            <ArrowRight size={11} />
          </button>
        }
      />
      <CardContent>
        <KpiStrip
          stats={[
            {
              label: t('field_clock.widget_on_site', { defaultValue: 'On site' }),
              value: data.on_site_count,
            },
            {
              label: t('field_clock.widget_pending', { defaultValue: 'To approve' }),
              value: data.pending_approvals,
              tone: data.pending_approvals > 0 ? 'text-semantic-warning' : 'text-content-secondary',
            },
            {
              label: t('field_clock.widget_missing', { defaultValue: 'No clock-out' }),
              value: data.missing_clock_outs,
              tone: data.missing_clock_outs > 0 ? 'text-semantic-warning' : 'text-content-secondary',
            },
          ]}
        />
      </CardContent>
    </Card>
  );
}

export default OnSiteNowCard;
