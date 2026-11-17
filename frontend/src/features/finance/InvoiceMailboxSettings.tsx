// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Mail } from 'lucide-react';
import { Button } from '@/shared/ui';
import { apiGet, apiPost, apiPut } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { isHostNotAllowed, mailboxDraftProblems, type MailboxDraft } from './invoiceMailboxRules';

interface MailboxSettings extends Omit<MailboxDraft, 'password'> {
  has_password: boolean;
  last_polled_at: string | null;
  last_error: string | null;
}

interface TestResult {
  ok: boolean;
  message_count: number | null;
  error: string | null;
}

const EMPTY: MailboxDraft = {
  enabled: false,
  host: '',
  port: 993,
  use_ssl: true,
  username: '',
  password: '',
  folder: 'INBOX',
  processed_folder: '',
  intake_address: '',
};

const inputCls = 'oe-input w-full';

/** IMAP mailbox the platform polls for scan-to-email invoices. Hidden without the configure permission. */
export function InvoiceMailboxSettings({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [draft, setDraft] = useState<MailboxDraft>(EMPTY);
  const [hasPassword, setHasPassword] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const query = useQuery({
    queryKey: ['finance-invoice-mailbox', projectId],
    queryFn: () => apiGet<MailboxSettings>(`/v1/finance/inbox/mailbox?project_id=${encodeURIComponent(projectId)}`),
    retry: false,
  });

  useEffect(() => {
    const s = query.data;
    if (!s) return;
    setDraft({ ...EMPTY, ...s, password: '' });
    setHasPassword(s.has_password);
  }, [query.data]);

  const set = <K extends keyof MailboxDraft>(key: K, value: MailboxDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));
  const [hostRefused, setHostRefused] = useState(false);

  const saveMut = useMutation({
    mutationFn: () =>
      apiPut<MailboxSettings>(`/v1/finance/inbox/mailbox?project_id=${encodeURIComponent(projectId)}`, draft),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['finance-invoice-mailbox', projectId] });
      queryClient.invalidateQueries({ queryKey: ['finance-invoice-intake-info', projectId] });
      addToast({ type: 'success', title: t('finance.inbox.mailbox_saved', { defaultValue: 'Mailbox settings saved' }) });
    },
    onError: (e: Error) => {
      if (isHostNotAllowed(e)) {
        setHostRefused(true);
        return;
      }
      addToast({
        type: 'error',
        title: t('finance.inbox.mailbox_invalid', { defaultValue: 'These mailbox settings are not valid' }),
        message: e.message,
      });
    },
  });

  const testMut = useMutation({
    mutationFn: () =>
      apiPost<TestResult>(`/v1/finance/inbox/mailbox/test?project_id=${encodeURIComponent(projectId)}`, {
        host: draft.host,
        port: draft.port,
        use_ssl: draft.use_ssl,
        username: draft.username,
        password: draft.password || null,
        folder: draft.folder,
      }),
    onSuccess: setTestResult,
    onError: (e: Error) => {
      if (isHostNotAllowed(e)) {
        setHostRefused(true);
        setTestResult(null);
        return;
      }
      setTestResult({ ok: false, message_count: null, error: e.message });
    },
  });

  // No permission (or no project access): the section does not exist for this user.
  if (query.isError || query.isLoading) return null;

  const problems = mailboxDraftProblems(draft, hasPassword);
  const label = (key: string, fallback: string) => t(`finance.inbox.mailbox_${key}`, { defaultValue: fallback });

  return (
    <details className="mt-3 rounded-lg border border-border-light p-3" data-testid="invoice-mailbox-settings">
      <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium text-content-primary">
        <Mail size={16} />
        {label('title', 'Mailbox for scan-to-email')}
      </summary>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input type="checkbox" checked={draft.enabled} onChange={(e) => set('enabled', e.target.checked)} />
          {label('enabled', 'Fetch invoices from this mailbox')}
        </label>
        <label className="text-sm">
          {label('host', 'IMAP server')}
          <input
            className={inputCls}
            value={draft.host}
            aria-invalid={hostRefused}
            onChange={(e) => {
              setHostRefused(false);
              set('host', e.target.value);
            }}
          />
          {hostRefused && (
            <span role="alert" className="mt-1 block text-xs text-semantic-error" data-testid="mailbox-host-refused">
              {label(
                'host_not_allowed',
                'This server address points to a private or internal network and is not allowed. Use the public IMAP address of your mail provider.',
              )}
            </span>
          )}
        </label>
        <label className="text-sm">
          {label('port', 'Port')}
          <input
            className={inputCls}
            type="number"
            value={draft.port}
            onChange={(e) => set('port', Number(e.target.value) || 0)}
          />
        </label>
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input type="checkbox" checked={draft.use_ssl} onChange={(e) => set('use_ssl', e.target.checked)} />
          {label('ssl', 'Use SSL/TLS')}
        </label>
        <label className="text-sm">
          {label('username', 'User name')}
          <input className={inputCls} value={draft.username} onChange={(e) => set('username', e.target.value)} />
        </label>
        <label className="text-sm">
          {label('password', 'Password')}
          <input
            className={inputCls}
            type="password"
            autoComplete="new-password"
            placeholder={hasPassword ? '••••••••' : ''}
            value={draft.password}
            onChange={(e) => set('password', e.target.value)}
          />
        </label>
        <label className="text-sm">
          {label('folder', 'Folder')}
          <input className={inputCls} value={draft.folder} onChange={(e) => set('folder', e.target.value)} />
        </label>
        <label className="text-sm">
          {label('processed_folder', 'Move processed mail to')}
          <input
            className={inputCls}
            value={draft.processed_folder}
            onChange={(e) => set('processed_folder', e.target.value)}
          />
        </label>
        <label className="text-sm sm:col-span-2">
          {label('intake_address', 'Address scanners send to')}
          <input
            className={inputCls}
            value={draft.intake_address}
            onChange={(e) => set('intake_address', e.target.value)}
          />
        </label>
      </div>
      {problems.length > 0 && (
        <p className="mt-2 text-xs text-semantic-warning">
          {label('invalid', 'These mailbox settings are not valid')}:{' '}
          {problems.map((p) => label(p, p)).join(', ')}
        </p>
      )}
      {testResult && (
        <p className={`mt-2 text-sm ${testResult.ok ? 'text-semantic-success' : 'text-semantic-error'}`}>
          {testResult.ok
            ? t('finance.inbox.mailbox_test_ok', {
                defaultValue: 'Connection works. Messages in the folder: {{n}}',
                n: testResult.message_count ?? 0,
              })
            : `${label('test_failed', 'Connection failed')}: ${testResult.error ?? ''}`}
        </p>
      )}
      {query.data?.last_polled_at && (
        <p className="mt-2 text-xs text-content-tertiary">
          {label('last_polled', 'Last checked')}: {query.data.last_polled_at}
          {query.data.last_error ? ` - ${query.data.last_error}` : ''}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <Button
          variant="secondary"
          onClick={() => testMut.mutate()}
          disabled={testMut.isPending || !draft.host || !draft.username}
        >
          {testMut.isPending && <Loader2 size={16} className="animate-spin" />}
          {label('test', 'Test connection')}
        </Button>
        <Button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || problems.length > 0}>
          {label('save', 'Save mailbox')}
        </Button>
      </div>
    </details>
  );
}
