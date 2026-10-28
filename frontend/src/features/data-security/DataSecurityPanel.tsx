// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// DataSecurityPanel (#4) - the trust posture made visible in-product.
//
// Reads GET /api/system/data-security and shows, in plain language, where this
// instance keeps its data and whether it reaches out anywhere: self-hosted,
// PostgreSQL + file storage on your own infrastructure, no bundled analytics,
// and AI that stays off unless an operator configures a provider (and then only
// the content you submit goes to that provider). Every value is read live from
// the running instance, so a self-hoster can verify the posture rather than
// take a marketing claim on trust. No secret is shown - AI is name + presence.

import { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  ShieldCheck,
  Server,
  Database,
  HardDrive,
  Sparkles,
  Lock,
  CheckCircle2,
  ExternalLink,
  AlertTriangle,
  Globe,
} from 'lucide-react';

import { Card, Badge, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { dataSecurityKeys, getDataSecurity } from './api';
import { fmtList } from '@/shared/lib/formatters';

function humanizeToken(token: string): string {
  return (token || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

interface FactProps {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  hint?: string;
  good?: boolean;
}

function Fact({ icon, label, value, hint, good }: FactProps) {
  return (
    <div className="flex items-start gap-3 py-2">
      <span className="mt-0.5 text-content-tertiary">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-content-primary">{label}</span>
          {good && <CheckCircle2 className="h-4 w-4 text-semantic-success" aria-hidden />}
        </div>
        <div className="mt-0.5 text-sm text-content-secondary">{value}</div>
        {hint && <p className="mt-0.5 text-xs text-content-tertiary">{hint}</p>}
      </div>
    </div>
  );
}

function SectionCard({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-oe-blue">{icon}</span>
        <h3 className="text-sm font-semibold text-content-primary">{title}</h3>
      </div>
      <div className="divide-y divide-border-light">{children}</div>
    </Card>
  );
}

export function DataSecurityPanel() {
  const { t } = useTranslation();
  const { data, isLoading, isError, error } = useQuery({
    queryKey: dataSecurityKeys.posture(),
    queryFn: getDataSecurity,
    staleTime: 5 * 60_000,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="space-y-3" data-testid="data-security-loading">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <Card className="p-4" data-testid="data-security-error">
        <p className="text-sm text-semantic-error">
          {t('dataSecurity.load_error', {
            defaultValue: 'Could not load the security posture: {{error}}',
            error: getErrorMessage(error),
          })}
        </p>
      </Card>
    );
  }

  const aiValue = data.ai.enabled
    ? t('dataSecurity.ai_on', {
        defaultValue: 'On - the content you submit goes to: {{providers}}',
        providers: fmtList(data.ai.providers),
      })
    : t('dataSecurity.ai_off', {
        defaultValue: 'Off - this instance makes no external AI calls',
      });

  return (
    <div className="space-y-4" data-testid="data-security-panel">
      <p className="text-sm text-content-secondary">
        {t('dataSecurity.intro', {
          defaultValue:
            'These facts are read live from this running instance, so you can verify the privacy posture rather than take it on trust.',
        })}
      </p>

      {data.demo_instance && (
        <div className="flex items-center gap-2 rounded-md border border-border-light bg-semantic-warning-bg px-3 py-2">
          <AlertTriangle className="h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
          <span className="text-xs text-content-secondary">
            {t('dataSecurity.demo_note', {
              defaultValue:
                'This is the public demo instance. A self-hosted install of the same software runs entirely on your own infrastructure.',
            })}
          </span>
        </div>
      )}

      <SectionCard
        icon={<ShieldCheck className="h-5 w-5" aria-hidden />}
        title={t('dataSecurity.deployment_title', { defaultValue: 'Deployment' })}
      >
        <Fact
          icon={<Server className="h-4 w-4" />}
          label={t('dataSecurity.self_hosted', { defaultValue: 'Self-hosted' })}
          value={
            data.self_hosted
              ? t('dataSecurity.self_hosted_yes', {
                  defaultValue: 'Yes - you run this software; there is no vendor-run cloud',
                })
              : t('common.no', { defaultValue: 'No' })
          }
          good={data.self_hosted}
        />
        <Fact
          icon={<Server className="h-4 w-4" />}
          label={t('dataSecurity.mode', { defaultValue: 'Run mode' })}
          value={
            data.deployment_mode === 'desktop'
              ? t('dataSecurity.mode_desktop', { defaultValue: 'Desktop app (single user, local)' })
              : t('dataSecurity.mode_server', { defaultValue: 'Server' })
          }
          hint={`${t('dataSecurity.version', { defaultValue: 'Version' })} ${data.version} - ${humanizeToken(
            data.environment,
          )}`}
        />
      </SectionCard>

      <SectionCard
        icon={<Database className="h-5 w-5" aria-hidden />}
        title={t('dataSecurity.residency_title', { defaultValue: 'Your data stays with you' })}
      >
        <Fact
          icon={<Database className="h-4 w-4" />}
          label={t('dataSecurity.database', { defaultValue: 'Database' })}
          value={`${humanizeToken(data.database.engine)} (${
            data.database.managed === 'external'
              ? t('dataSecurity.db_external', { defaultValue: 'your external PostgreSQL' })
              : t('dataSecurity.db_embedded', { defaultValue: 'bundled, runs in place' })
          })`}
          good={data.database.on_your_infrastructure}
        />
        <Fact
          icon={<HardDrive className="h-4 w-4" />}
          label={t('dataSecurity.storage', { defaultValue: 'File storage' })}
          value={
            data.storage.backend === 's3'
              ? t('dataSecurity.storage_s3', { defaultValue: 'Your own S3-compatible bucket' })
              : t('dataSecurity.storage_local', { defaultValue: 'Local filesystem on this server' })
          }
          good={data.storage.on_your_infrastructure}
        />
        <Fact
          icon={<ShieldCheck className="h-4 w-4" />}
          label={t('dataSecurity.analytics', { defaultValue: 'Usage analytics' })}
          value={
            data.analytics_bundled
              ? t('dataSecurity.analytics_on', { defaultValue: 'Present' })
              : t('dataSecurity.analytics_off', {
                  defaultValue: 'None - the application ships no third-party tracking',
                })
          }
          good={!data.analytics_bundled}
        />
      </SectionCard>

      <SectionCard
        icon={<Sparkles className="h-5 w-5" aria-hidden />}
        title={t('dataSecurity.ai_title', { defaultValue: 'AI' })}
      >
        <Fact
          icon={<Sparkles className="h-4 w-4" />}
          label={t('dataSecurity.ai_status', { defaultValue: 'AI features' })}
          value={aiValue}
          good={!data.ai.external_calls}
          hint={
            data.ai.offline_capable
              ? t('dataSecurity.ai_offline', {
                  defaultValue:
                    'The platform runs fully offline; AI reaches out only to a provider you configure.',
                })
              : undefined
          }
        />
        {data.ai.enabled && data.ai.providers.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 py-2">
            {data.ai.providers.map((p) => (
              <Badge key={p} variant="blue" size="sm">
                {p}
              </Badge>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard
        icon={<Lock className="h-5 w-5" aria-hidden />}
        title={t('dataSecurity.access_title', { defaultValue: 'Access and source' })}
      >
        <Fact
          icon={<Globe className="h-4 w-4" />}
          label={t('dataSecurity.registration', { defaultValue: 'Self-registration' })}
          value={humanizeToken(data.registration_mode)}
        />
        <Fact
          icon={<CheckCircle2 className="h-4 w-4" />}
          label={t('dataSecurity.license', { defaultValue: 'License' })}
          value={data.source.license}
          good
        />
        <Fact
          icon={<ExternalLink className="h-4 w-4" />}
          label={t('dataSecurity.source', { defaultValue: 'Source code' })}
          value={
            <a
              href={data.source.repository}
              target="_blank"
              rel="noreferrer"
              className="text-oe-blue hover:underline"
            >
              {t('dataSecurity.source_link', { defaultValue: 'Open on GitHub' })}
            </a>
          }
        />
      </SectionCard>
    </div>
  );
}

export default DataSecurityPanel;
