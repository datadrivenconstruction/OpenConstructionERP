import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, FileArchive, Info, Trash2, Upload, XCircle } from 'lucide-react';
import { Badge, Button, Card } from '@/shared/ui';
import { apiDelete, apiGet, apiPost, API_BASE, fetchWithAuth, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { RUNTIME_UI_ENTRIES_KEY } from './runtimeModules';

interface PackageCheck {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
}

interface PackagePreview {
  token: string;
  archive_sha256: string;
  archive_size: number;
  module_name: string | null;
  version: string | null;
  display_name: string | null;
  author: string | null;
  depends: string[];
  requires_platform: string | null;
  ui: { label: string; mode: string; path: string; group: string } | null;
  files: { path: string; size: number; sha256: string }[];
  checks: PackageCheck[];
  installable: boolean;
}

interface InstalledPackage {
  name: string;
  version: string | null;
  display_name: string | null;
  archive_sha256: string;
  installed_at: string;
  loaded: boolean;
  enabled: boolean;
}

interface InstallResult {
  name: string;
  status: 'active' | 'installed_disabled';
}

const INSTALLED_KEY = ['module-packages-installed'] as const;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Admin-only: upload a third-party module ZIP, review every file and every
 * check, confirm that the code is trusted, then install. Same trust model as
 * the module builder: nothing runs before the administrator clicks Install.
 */
export function ModulePackagesPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const inputRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<PackagePreview | null>(null);
  const [trusted, setTrusted] = useState(false);
  const [enable, setEnable] = useState(true);
  const [uploading, setUploading] = useState(false);

  const { data: installed } = useQuery({
    queryKey: INSTALLED_KEY,
    queryFn: () => apiGet<InstalledPackage[]>('/v1/module-packages/installed'),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: INSTALLED_KEY });
    void queryClient.invalidateQueries({ queryKey: ['system-modules'] });
    void queryClient.invalidateQueries({ queryKey: RUNTIME_UI_ENTRIES_KEY });
  };

  const upload = async (file: File) => {
    setUploading(true);
    setPreview(null);
    setTrusted(false);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetchWithAuth(`${API_BASE}/v1/module-packages/preview`, { method: 'POST', body: form });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : res.statusText);
      setPreview(body as PackagePreview);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('module_packages.upload_failed', { defaultValue: 'The archive was refused' }),
        message: getErrorMessage(err),
      });
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const install = useMutation({
    mutationFn: (p: PackagePreview) =>
      apiPost<InstallResult>(`/v1/module-packages/${p.token}/install`, { confirm_trusted: trusted, enable }),
    onSuccess: (result) => {
      addToast({
        type: 'success',
        title:
          result.status === 'active'
            ? t('module_packages.installed_active', { defaultValue: 'Module installed and active' })
            : t('module_packages.installed_disabled', { defaultValue: 'Module installed, switched off' }),
        message: result.name,
      });
      setPreview(null);
      refresh();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('module_packages.install_failed', { defaultValue: 'Install failed, nothing was changed' }),
        message: getErrorMessage(err),
      });
    },
  });

  const remove = useMutation({
    mutationFn: (name: string) => apiDelete(`/v1/module-packages/installed/${name}`),
    onSuccess: refresh,
    onError: (err) => addToast({ type: 'error', title: t('module_packages.uninstall_failed', { defaultValue: 'Could not uninstall' }), message: getErrorMessage(err) }),
  });

  const discard = () => {
    if (preview) void apiDelete(`/v1/module-packages/${preview.token}`).catch(() => undefined);
    setPreview(null);
  };

  return (
    <Card className="mb-5 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <FileArchive size={16} />
            {t('module_packages.title', { defaultValue: 'Install module (.zip)' })}
          </h3>
          <p className="mt-1 max-w-2xl text-xs text-content-secondary">
            {t('module_packages.intro', {
              defaultValue:
                'A module package contains Python that runs on the server with full access to your data. Install only modules from publishers you trust. Every file is shown for review before anything runs.',
            })}
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
          }}
        />
        <Button variant="secondary" size="sm" disabled={uploading} onClick={() => inputRef.current?.click()}>
          <Upload size={14} className="mr-1.5" />
          {uploading
            ? t('module_packages.checking', { defaultValue: 'Checking...' })
            : t('module_packages.choose', { defaultValue: 'Choose ZIP' })}
        </Button>
      </div>

      {preview && (
        <div className="mt-4 space-y-3 border-t border-border pt-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium text-content-primary">{preview.display_name ?? preview.module_name ?? '?'}</span>
            {preview.version && <Badge variant="neutral">{preview.version}</Badge>}
            {preview.module_name && <code className="text-xs text-content-tertiary">{preview.module_name}</code>}
            {preview.author && <span className="text-xs text-content-secondary">{preview.author}</span>}
            <Badge variant="neutral">
              {preview.ui
                ? t('module_packages.mode_hosted', { defaultValue: 'Embedded page' })
                : t('module_packages.mode_none', { defaultValue: 'No page (API only)' })}
            </Badge>
          </div>
          <p className="break-all text-2xs text-content-tertiary">
            SHA-256 {preview.archive_sha256} · {formatSize(preview.archive_size)}
          </p>

          <ul className="space-y-1">
            {preview.checks.map((c, i) => (
              <li key={`${c.rule_id}-${i}`} className="flex items-start gap-2 text-xs">
                {c.severity === 'error' ? (
                  <XCircle size={14} className="mt-0.5 shrink-0 text-semantic-error" />
                ) : c.severity === 'warning' ? (
                  <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" />
                ) : (
                  <Info size={14} className="mt-0.5 shrink-0 text-content-tertiary" />
                )}
                <span className="text-content-secondary">{c.message}</span>
              </li>
            ))}
            {preview.installable && (
              <li className="flex items-center gap-2 text-xs text-semantic-success">
                <CheckCircle2 size={14} />
                {t('module_packages.checks_passed', { defaultValue: 'All required checks passed.' })}
              </li>
            )}
          </ul>

          <details open className="rounded border border-border">
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-content-primary">
              {t('module_packages.files', { defaultValue: 'Files to review ({{count}})', count: preview.files.length })}
            </summary>
            <table className="w-full text-2xs">
              <tbody>
                {preview.files.map((f) => (
                  <tr key={f.path} className="border-t border-border">
                    <td className="px-3 py-1 font-mono text-content-primary">{f.path}</td>
                    <td className="px-3 py-1 text-right text-content-secondary">{formatSize(f.size)}</td>
                    <td className="hidden px-3 py-1 font-mono text-content-tertiary md:table-cell">{f.sha256.slice(0, 16)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>

          {preview.installable && (
            <div className="space-y-2">
              <label className="flex items-start gap-2 text-xs text-content-primary">
                <input type="checkbox" checked={trusted} onChange={(e) => setTrusted(e.target.checked)} className="mt-0.5" />
                {t('module_packages.confirm_trust', {
                  defaultValue: 'I reviewed these files and I trust this code to run on the server.',
                })}
              </label>
              <label className="flex items-center gap-2 text-xs text-content-secondary">
                <input type="checkbox" checked={enable} onChange={(e) => setEnable(e.target.checked)} />
                {t('module_packages.enable_now', { defaultValue: 'Switch the module on after installing' })}
              </label>
            </div>
          )}
          <div className="flex gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={!preview.installable || !trusted || install.isPending}
              onClick={() => install.mutate(preview)}
            >
              {t('module_packages.install', { defaultValue: 'Install' })}
            </Button>
            <Button variant="ghost" size="sm" onClick={discard}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}

      {(installed?.length ?? 0) > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          <p className="mb-2 text-xs font-medium text-content-secondary">
            {t('module_packages.installed_list', { defaultValue: 'Installed from ZIP' })}
          </p>
          <ul className="space-y-1">
            {installed?.map((m) => (
              <li key={m.name} className="flex items-center justify-between gap-2 text-xs">
                <span className="text-content-primary">
                  {m.display_name ?? m.name} <span className="text-content-tertiary">{m.version}</span>{' '}
                  <Badge variant={m.loaded && m.enabled ? 'success' : 'neutral'}>
                    {m.loaded && m.enabled
                      ? t('module_packages.status_active', { defaultValue: 'Active' })
                      : t('module_packages.status_off', { defaultValue: 'Off' })}
                  </Badge>
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (window.confirm(t('module_packages.uninstall_confirm', { defaultValue: 'Uninstall {{name}}? Its files are removed; its data tables are kept.', name: m.display_name ?? m.name }))) remove.mutate(m.name);
                  }}
                >
                  <Trash2 size={14} className="mr-1" />
                  {t('module_packages.uninstall', { defaultValue: 'Uninstall' })}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
