/** Right rail showing details of the currently-focused file. */

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Download, Mail, FolderOpen, Copy, X, FileText, Image as ImageIcon, Layout, Box, Pencil, File, PenTool, FileBarChart, Tag, ExternalLink, Activity, Share2, Lock, Send, ClipboardCheck, CheckCircle2, Link as LinkIcon, History, RotateCcw, Loader2, Check, ChevronDown } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet } from '@/shared/lib/api';
import type { FileRow, FileKind } from '../types';
import { downloadProtectedFile, fetchProtectedObjectUrl } from '../api';
import { isTauri, openInOSFinder, copyToClipboard } from '../lib/tauri';
import { modulesForKind, primaryModule } from '../kindModule';
import { useSetDocumentCdeState } from '../hooks';
import type { CdeState } from '../api';
import { CDE_BADGE } from './CDEBadge';
import { ActivityDrawer } from './ActivityDrawer';
import { VersionDropdown } from '@/features/file-versions/VersionDropdown';
import { useFileVersions, useRestoreVersion } from '@/features/file-versions/hooks';
import { VersionBadge } from '@/features/file-versions/VersionBadge';
import type { FileVersionResponse } from '@/features/file-versions/types';
import { CommentThread } from '@/features/file-comments/CommentThread';
import { NamingViolationBanner } from '@/features/file-references/NamingViolationBanner';
import { ReferencedInPanel } from '@/features/file-references/ReferencedInPanel';
import { LinkToEntityModal } from '@/features/file-references/LinkToEntityModal';
import { NewTransmittalWizard } from '@/features/file-transmittals/NewTransmittalWizard';
import { SubmitForApprovalModal } from '@/features/file-approvals/SubmitForApprovalModal';
import { ApprovalDrawer } from '@/features/file-approvals/ApprovalDrawer';
import { useApprovals } from '@/features/file-approvals/hooks';

const KIND_ICON: Record<FileKind, typeof FileText> = {
  document: FileText,
  photo: ImageIcon,
  sheet: Layout,
  bim_model: Box,
  dwg_drawing: Pencil,
  takeoff: Tag,
  report: FileBarChart,
  markup: PenTool,
};

interface FilePreviewPaneProps {
  row: FileRow | null;
  onClose: () => void;
  onEmail: (row: FileRow) => void;
  onShare?: (row: FileRow) => void;
  /** Owner-only: opens FolderPermissionsModal scoped to this row's kind. */
  onManageAccess?: (row: FileRow) => void;
}

function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/* Inline preview probe — relies on file extension first (cheap, exact)
   and falls back to mime sniff for documents uploaded without a .pdf
   suffix. The native browser PDF viewer renders via <iframe>; we drop
   the chrome with #toolbar=0&navpanes=0&view=FitH so the pane reads as
   a thumbnail rather than a full reader. */
function isPdf(row: FileRow): boolean {
  if (row.extension && row.extension.toLowerCase().replace(/^\./, '') === 'pdf') return true;
  if (row.mime_type && row.mime_type.toLowerCase() === 'application/pdf') return true;
  return false;
}

export function FilePreviewPane({ row, onClose, onEmail, onShare, onManageAccess }: FilePreviewPaneProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const ctxProjectId = useProjectContextStore((s) => s.activeProjectId);
  const ctxProjectName = useProjectContextStore((s) => s.activeProjectName);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  // Shared cache (same key BIMPage uses) — lets us label the project
  // context correctly when jumping to a file in a project that isn't the
  // currently-active one (global /files view).
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Array<{ id: string; name: string }>>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });
  const [pathCopied, setPathCopied] = useState(false);
  const [downloading, setDownloading] = useState(false);
  // Authenticated inline PDF preview. The download endpoint is bearer-protected,
  // so a raw `<iframe src>` navigation 401s (no Authorization header); fetch the
  // bytes with the header and preview the resulting blob URL instead.
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState<string | null>(null);
  const previewDownloadUrl = row && isPdf(row) ? row.download_url : null;
  useEffect(() => {
    if (!previewDownloadUrl) {
      setPdfPreviewUrl(null);
      return;
    }
    let cancelled = false;
    let created: string | null = null;
    setPdfPreviewUrl(null);
    void fetchProtectedObjectUrl(previewDownloadUrl).then((objUrl) => {
      if (cancelled) {
        if (objUrl) URL.revokeObjectURL(objUrl);
        return;
      }
      created = objUrl;
      setPdfPreviewUrl(objUrl);
    });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [previewDownloadUrl]);
  // Slide-over drawer with the full audit timeline. Opens on demand so
  // we don't fire the activity request for every previewed file —
  // unlike the inline ``ActivityLogSection`` below which renders a
  // compact "last few events" strip eagerly.
  const [activityOpen, setActivityOpen] = useState(false);
  const [transmittalOpen, setTransmittalOpen] = useState(false);
  const [submitApprovalOpen, setSubmitApprovalOpen] = useState(false);
  const [approvalDrawerOpen, setApprovalDrawerOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);

  // Find any active approval workflow for the current file so the
  // "Approval status" entry shows up only when relevant.
  const { data: projectWorkflows = [] } = useApprovals(row?.project_id);
  const activeWorkflow = row
    ? projectWorkflows.find(
        (w) =>
          w.file_kind === row.kind &&
          w.file_id === row.id &&
          w.status === 'in_review',
      )
    : undefined;

  if (!row) {
    return (
      <aside className="w-80 shrink-0 border-l border-border-light bg-surface-secondary/40 flex items-center justify-center">
        <p className="text-xs text-content-tertiary px-4 text-center">
          {t('files.preview.empty', {
            defaultValue: 'Select a file to see details.',
          })}
        </p>
      </aside>
    );
  }

  const Icon = KIND_ICON[row.kind] ?? File;
  // Primary tool for this file's extension (e.g. PDF → PDF Takeoff,
  // IFC → BIM Viewer, DWG → DWG Takeoff). Falls back to the kind's
  // default module when the extension isn't in the override map.
  const primary = primaryModule(row.kind, row.extension);
  const allModules = modulesForKind(row.kind, row.extension);
  const PrimaryIcon = primary.icon;
  // `row` is narrowed by the `if (!row) return` guard above, but TS
  // doesn't carry that narrowing into nested function declarations —
  // capture it in a const so closures see the non-null type.
  const file = row;

  async function handleDownload() {
    if (!file.download_url) return;
    setDownloading(true);
    try {
      await downloadProtectedFile(file.download_url, file.name);
    } catch (e) {
      addToast({
        type: 'error',
        title: t('files.actions.download_failed', { defaultValue: 'Could not download the file' }),
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setDownloading(false);
    }
  }

  function navigateToModule(target: typeof primary) {
    // Clash Detection / CAD-BIM BI Explorer read the project from the
    // global context store, not a path param — bind it to this file's
    // project first so the destination opens populated instead of on the
    // empty "no active project" state. Reuse the already-known context
    // name when it's the same project; otherwise resolve the real name
    // from the (cached) projects list so the global project selector
    // never shows a blank label after the jump.
    if (target.setsActiveProject) {
      const resolved =
        ctxProjectId === file.project_id
          ? ctxProjectName
          : projects.find((p) => p.id === file.project_id)?.name ?? ctxProjectName;
      setActiveProject(file.project_id, resolved);
    }
    navigate(target.route(file.project_id, file.id));
  }

  async function handleCopyPath() {
    if (!row) return;
    const ok = await copyToClipboard(row.physical_path);
    if (ok) {
      setPathCopied(true);
      setTimeout(() => setPathCopied(false), 1500);
    } else {
      addToast({
        type: 'error',
        title: t('files.toast.copy_failed', { defaultValue: 'Could not copy path' }),
      });
    }
  }

  // Surfaced inline next to the size rather than as a raw metadata row.
  const sizeIsConvertedArtifact = row.extra?.size_is_converted_artifact === true;
  const extras = Object.entries(row.extra ?? {}).filter(
    ([k, v]) =>
      v !== null && v !== undefined && v !== '' && k !== 'size_is_converted_artifact',
  );

  return (
    <aside className="w-80 shrink-0 border-l border-border-light bg-surface-elevated overflow-y-auto">
      <div className="sticky top-0 z-10 flex items-center justify-between px-4 py-2.5 border-b border-border-light bg-surface-elevated">
        <span className="text-xs font-semibold text-content-primary truncate">
          {t('files.preview.title', { defaultValue: 'File details' })}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('common.close', { defaultValue: 'Close' })}
          className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
        >
          <X size={14} />
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* W9 — ISO 19650 naming-violation banner. Renders null when the
            file's canonical name is compliant, so it stays out of the way. */}
        <NamingViolationBanner
          projectId={row.project_id}
          fileKind={row.kind}
          fileId={row.id}
          className="mb-1"
        />
        <div className="flex items-center justify-center overflow-hidden bg-surface-secondary/60 rounded-lg aspect-[4/3]">
          {isPdf(row) && row.download_url ? (
            pdfPreviewUrl ? (
              <iframe
                src={`${pdfPreviewUrl}#toolbar=0&navpanes=0&view=FitH`}
                title={row.name}
                className="h-full w-full border-0 rounded-lg"
              />
            ) : (
              <Loader2 size={28} className="animate-spin text-content-tertiary" />
            )
          ) : row.thumbnail_url ? (
            <img
              src={row.thumbnail_url}
              alt=""
              className="max-h-full max-w-full object-contain rounded-lg"
            />
          ) : (
            <Icon size={48} strokeWidth={1.5} className="text-content-tertiary" />
          )}
        </div>

        <div>
          <h3 className="text-sm font-semibold text-content-primary break-words" title={row.name}>
            {row.name}
          </h3>
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {fmtBytes(row.size_bytes)}
            {sizeIsConvertedArtifact && (
              <span
                className="ms-1.5 text-content-quaternary"
                title={t('files.detail.size_converted_artifact_hint', {
                  defaultValue:
                    'The original source upload is unavailable; this is the size of the converted geometry artifact.',
                })}
              >
                {t('files.detail.size_converted_artifact', {
                  defaultValue: '(converted artifact)',
                })}
              </span>
            )}
            {row.mime_type && <span className="ms-2">{row.mime_type}</span>}
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          {/* Primary action — opens this file in its native module. PDFs
              go to PDF Takeoff or Documents Viewer; IFC/RVT to BIM
              Viewer; DWG to DWG Takeoff. Falls back to download below
              when the user just wants the bytes. */}
          <button
            type="button"
            onClick={() => navigateToModule(primary)}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold bg-oe-blue text-white hover:bg-oe-blue-hover transition-colors"
            title={t(primary.descriptionI18nKey, { defaultValue: primary.description })}
          >
            <PrimaryIcon size={13} strokeWidth={2.25} />
            {t('files.actions.open_in', {
              defaultValue: 'Open in {{module}}',
              module: t(primary.i18nKey, { defaultValue: primary.label }),
            })}
            <ExternalLink size={11} className="opacity-80" />
          </button>

          {/* Secondary modules — same file, different tool (e.g. a PDF
              also opens in Documents Viewer; an IFC also feeds BIM
              Rules). Skipped when there's only one possibility. */}
          {allModules.length > 1 && (
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {allModules
                .filter((m) => m.label !== primary.label)
                .map((m) => {
                  const MIcon = m.icon;
                  return (
                    <button
                      key={m.label}
                      type="button"
                      onClick={() => navigateToModule(m)}
                      className={clsx(
                        'inline-flex items-center gap-1 h-6 px-2 rounded-md text-[10.5px] font-medium transition-colors',
                        'border border-border-light text-content-secondary',
                        'hover:border-oe-blue/40 hover:text-oe-blue hover:bg-oe-blue/5',
                      )}
                      title={t(m.descriptionI18nKey, { defaultValue: m.description })}
                    >
                      <MIcon size={10} strokeWidth={2} />
                      {t(m.i18nKey, { defaultValue: m.label })}
                    </button>
                  );
                })}
            </div>
          )}

          {row.download_url && (
            <button
              type="button"
              onClick={handleDownload}
              disabled={downloading}
              className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-border-light text-content-primary hover:bg-surface-secondary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {downloading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
              {t('files.actions.download', { defaultValue: 'Download' })}
            </button>
          )}
          {/* W1 — version history. Renders <V## · Current> chip + dropdown
              with a "Make current" action for every superseded row. */}
          <div className="flex items-center justify-between gap-2 px-1 py-1 border-y border-border-light/60">
            <span className="text-[10px] uppercase tracking-wider text-content-tertiary font-medium">
              {t('files.versions.section_label', { defaultValue: 'Versions' })}
            </span>
            <VersionDropdown fileId={row.id} kind={row.kind} />
          </div>
          {/* Document lifecycle (CDE) status. Set WIP / Shared / Published /
              Archived inline via PATCH /v1/documents/{id}. Only documents are
              backed by that table, so the control is gated to that kind. */}
          {row.kind === 'document' && (
            <div className="flex items-center justify-between gap-2 px-1 py-1 border-b border-border-light/60">
              <span className="text-[10px] uppercase tracking-wider text-content-tertiary font-medium">
                {t('files.status.label', { defaultValue: 'Status' })}
              </span>
              <CdeStatusControl
                projectId={row.project_id}
                documentId={row.id}
                current={
                  typeof row.extra?.cde_state === 'string'
                    ? (row.extra.cde_state as string)
                    : null
                }
              />
            </div>
          )}
          <button
            type="button"
            onClick={() => onEmail(row)}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-border-light text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <Mail size={13} />
            {t('files.actions.email', { defaultValue: 'Email link' })}
          </button>
          {/* W7 — Send transmittal (formal AEC issue record). */}
          <button
            type="button"
            onClick={() => setTransmittalOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-border-light text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <Send size={13} />
            {t('files.transmittals.send_action', { defaultValue: 'Send transmittal' })}
          </button>
          {/* W8 — Submit for approval / View approval status. */}
          <button
            type="button"
            onClick={() => setSubmitApprovalOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-border-light text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <ClipboardCheck size={13} />
            {t('files.approvals.submit_action', { defaultValue: 'Submit for approval' })}
          </button>
          {activeWorkflow && (
            <button
              type="button"
              onClick={() => setApprovalDrawerOpen(true)}
              className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-oe-blue/30 bg-oe-blue/5 text-oe-blue hover:bg-oe-blue/10 transition-colors"
            >
              <CheckCircle2 size={13} />
              {t('files.approvals.view_status', { defaultValue: 'Approval status' })}
            </button>
          )}
          {/* W9 — Link this file to an RFI / task / change-order etc. */}
          <button
            type="button"
            onClick={() => setLinkOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-border-light text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <LinkIcon size={13} />
            {t('files.references.link_action', { defaultValue: 'Link to entity' })}
          </button>
          {onShare && row.kind === 'document' && (
            <button
              type="button"
              onClick={() => onShare(row)}
              data-testid="file-share-button"
              className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-border-light text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <Share2 size={13} />
              {t('files.actions.share', { defaultValue: 'Share' })}
            </button>
          )}
          {/* Activity drawer trigger — visible for any file kind, but
              the drawer itself gracefully renders an empty / 404 state
              for non-document backings. */}
          <button
            type="button"
            onClick={() => setActivityOpen(true)}
            data-testid="file-activity-button"
            className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-border-light text-content-primary hover:bg-surface-secondary transition-colors"
            title={t('files.activity.open', { defaultValue: 'View activity history' })}
          >
            <Activity size={13} />
            {t('files.activity.open', { defaultValue: 'View activity history' })}
          </button>
          {onManageAccess && (
            <button
              type="button"
              onClick={() => onManageAccess(row)}
              data-testid="file-manage-access-button"
              className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-border-light text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <Lock size={13} />
              {t('files.permissions.manage', { defaultValue: 'Manage access' })}
            </button>
          )}
          {isTauri && row.physical_path && (
            <button
              type="button"
              onClick={() => openInOSFinder(row.physical_path)}
              className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-border-light text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <FolderOpen size={13} />
              {t('files.actions.open_in_os', { defaultValue: 'Open in OS' })}
            </button>
          )}
        </div>

        <dl className="space-y-2 text-xs">
          <Row label={t('files.detail.kind', { defaultValue: 'Kind' })}>
            {t(`files.category.${row.kind}`, { defaultValue: row.kind })}
          </Row>
          {row.category && (
            <Row label={t('files.detail.category', { defaultValue: 'Category' })}>
              {row.category}
            </Row>
          )}
          {row.discipline && (
            <Row label={t('files.detail.discipline', { defaultValue: 'Discipline' })}>
              {row.discipline}
            </Row>
          )}
          {row.modified_at && (
            <Row label={t('files.detail.modified', { defaultValue: 'Modified' })}>
              <DateDisplay value={row.modified_at} format="datetime" />
            </Row>
          )}
          <Row label={t('files.detail.storage', { defaultValue: 'Storage' })}>
            <span className="uppercase tracking-wide text-2xs">{row.storage_backend}</span>
          </Row>
          <Row label={t('files.detail.path', { defaultValue: 'Path' })}>
            <button
              type="button"
              onClick={handleCopyPath}
              className="inline-flex items-center gap-1 font-mono text-[10px] text-content-secondary hover:text-oe-blue text-left break-all"
              title={t('files.actions.copy_path', { defaultValue: 'Copy path' })}
            >
              <Copy size={10} className="shrink-0" />
              {pathCopied
                ? t('files.toast.copied', { defaultValue: 'Copied' })
                : row.physical_path}
            </button>
          </Row>
        </dl>

        {extras.length > 0 && (
          <div className="border-t border-border-light pt-3">
            <h4 className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-2">
              {t('files.detail.extra', { defaultValue: 'Metadata' })}
            </h4>
            <dl className="space-y-1.5 text-xs">
              {extras.map(([k, v]) => (
                <Row key={k} label={k.replace(/_/g, ' ')}>
                  <span className="font-mono text-[11px] break-words">
                    {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  </span>
                </Row>
              ))}
            </dl>
          </div>
        )}

        {/* Per-file audit timeline. The activity endpoint lives on the
            ``oe_documents_document`` table, so it only resolves for
            document-backed kinds (document / sheet / photo). For other
            kinds (bim_model / dwg / takeoff / report / markup) the id is
            not a valid document id and the request would 404, so we skip
            it entirely rather than firing a guaranteed-404 query.
            The compact in-pane strip stays for at-a-glance scanning;
            the full timeline lives in the slide-over drawer below. */}
        <ActivityLogSection documentId={row.id} kind={row.kind} />

        {/* W9 — "Referenced in" panel. Lists all RFIs / tasks / change
            orders / etc. that link to this file. */}
        <ReferencedInPanel
          projectId={row.project_id}
          fileKind={row.kind}
          fileId={row.id}
          onChipClick={(ref) => {
            const targetRoute: Record<string, string> = {
              rfi: '/rfi',
              task: '/tasks',
              change_order: '/changeorders',
              punch_item: '/punchlist',
              field_report: '/field-reports',
              submittal: '/submittals',
              meeting: '/meetings',
            };
            const base = targetRoute[ref.target_type] ?? `/${ref.target_type}`;
            navigate(`${base}/${ref.target_id}`);
          }}
          className="mt-3"
        />

        {/* W6 — Threaded comments on this file. Lazily fires its own
            query so the strip stays cheap until the pane is open. */}
        <CommentThread
          projectId={row.project_id}
          fileKind={row.kind}
          fileId={row.id}
          currentUserId={null}
          className="mt-3"
        />

        {/* W1 — chronological version history with per-row download +
            restore buttons. Sits next to the Activity / Referenced-in /
            Comments sections so the preview pane reads as a single
            scroll surface ("tabs" in the same flat-section vocabulary
            the rest of the pane already uses). */}
        <VersionHistorySection fileId={row.id} kind={row.kind} />
      </div>

      {/* Full audit timeline as a right-edge slide-over. Mounted at the
          end of the aside so it overlays the pane (and the rest of the
          page via its own fixed positioning) without disrupting the
          preview layout. */}
      <ActivityDrawer
        documentId={row.id}
        documentName={row.name}
        open={activityOpen}
        onClose={() => setActivityOpen(false)}
      />

      {/* W7 — Transmittal wizard (preselected with this single file). */}
      <NewTransmittalWizard
        open={transmittalOpen}
        onClose={() => setTransmittalOpen(false)}
        projectId={row.project_id}
        preselectedItems={[
          {
            file_kind: row.kind,
            file_id: row.id,
            canonical_name_snapshot: row.name,
          },
        ]}
      />

      {/* W8 — Submit-for-approval modal + workflow drawer. */}
      <SubmitForApprovalModal
        open={submitApprovalOpen}
        onClose={() => setSubmitApprovalOpen(false)}
        projectId={row.project_id}
        fileKind={row.kind}
        fileId={row.id}
        fileLabel={row.name}
      />
      <ApprovalDrawer
        open={approvalDrawerOpen}
        workflowId={activeWorkflow?.id ?? null}
        onClose={() => setApprovalDrawerOpen(false)}
      />

      {/* W9 — Link-to-entity modal. */}
      <LinkToEntityModal
        open={linkOpen}
        projectId={row.project_id}
        fileKind={row.kind}
        fileId={row.id}
        onClose={() => setLinkOpen(false)}
      />
    </aside>
  );
}

/* ── Activity log timeline ─────────────────────────────────────────────
   Backend endpoint: GET /v1/documents/{id}/activity/?limit=20. Returns
   newest-first audit events for the document (upload / rename / cde
   state change / delete). Renders a vertical timeline keyed by action,
   with the action chip colour-coded so a quick glance tells the user
   what happened. Gracefully renders nothing on 404 / error so an
   un-migrated backend can't break the preview pane. */
interface ActivityEvent {
  id: string;
  document_id: string;
  user_id: string | null;
  action: string;
  meta: Record<string, unknown>;
  created_at: string;
}

const ACTIVITY_ACTION_STYLE: Record<string, string> = {
  uploaded: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300',
  renamed: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
  downloaded: 'bg-surface-secondary text-content-secondary',
  deleted: 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300',
  cde_state_changed: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
};

function formatActivityMeta(action: string, meta: Record<string, unknown>): string {
  /* Render a short, locale-neutral summary of the JSON meta blob. The
     parent caller turns this into a localised label when the action is
     well-known; unknown actions fall through to an empty string and the
     chip alone tells the user what happened. */
  if (action === 'renamed') {
    const oldName = typeof meta.old === 'string' ? meta.old : '';
    const newName = typeof meta.new === 'string' ? meta.new : '';
    if (oldName && newName) return `${oldName} → ${newName}`;
  }
  if (action === 'cde_state_changed') {
    const oldState = typeof meta.old === 'string' ? meta.old : 'wip';
    const newState = typeof meta.new === 'string' ? meta.new : '';
    if (newState) return `${oldState} → ${newState}`;
  }
  if (action === 'uploaded') {
    const name = typeof meta.name === 'string' ? meta.name : '';
    return name;
  }
  if (action === 'deleted') {
    const name = typeof meta.name === 'string' ? meta.name : '';
    return name;
  }
  return '';
}

// Only these kinds are backed by the ``oe_documents_document`` table that
// owns the /documents/{id}/activity endpoint. Other kinds carry ids from
// their own modules (BIM models, DWG drawings, takeoff sessions, …) that
// are not valid document ids, so the activity query is disabled for them.
const ACTIVITY_BACKED_KINDS: ReadonlySet<FileKind> = new Set<FileKind>([
  'document',
  'sheet',
  'photo',
]);

function ActivityLogSection({ documentId, kind }: { documentId: string; kind: FileKind }) {
  const { t } = useTranslation();
  const enabled = ACTIVITY_BACKED_KINDS.has(kind);
  const { data, isLoading, isError } = useQuery({
    queryKey: ['document-activity', documentId],
    queryFn: () =>
      apiGet<ActivityEvent[]>(`/v1/documents/${documentId}/activity/?limit=20`),
    staleTime: 30_000,
    retry: false,
    enabled,
  });
  /* Not a document-backed kind → never fire the request (it would 404). */
  if (!enabled) return null;
  /* 404 / 5xx must never break the pane — the endpoint is new and may
     legitimately be missing on an un-migrated backend. */
  if (isError) return null;
  const events = data ?? [];
  if (!isLoading && events.length === 0) return null;
  return (
    <div className="border-t border-border-light pt-3">
      <h4 className="flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-2">
        <Activity size={11} strokeWidth={2} />
        {t('files.detail.activity', { defaultValue: 'Activity' })}
        {events.length > 0 && (
          <span className="ms-1 text-content-quaternary tabular-nums">({events.length})</span>
        )}
      </h4>
      {isLoading ? (
        <div className="h-3 rounded bg-surface-secondary animate-pulse" />
      ) : (
        <ol className="relative space-y-2 ps-3 before:absolute before:top-1 before:bottom-1 before:start-1 before:w-px before:bg-border-light">
          {events.map((ev) => {
            const chipStyle =
              ACTIVITY_ACTION_STYLE[ev.action] ?? 'bg-surface-secondary text-content-secondary';
            const summary = formatActivityMeta(ev.action, ev.meta ?? {});
            const actionLabel = t(`files.activity.action.${ev.action}`, {
              defaultValue: ev.action.replace(/_/g, ' '),
            });
            return (
              <li key={ev.id} className="relative">
                <span className="absolute -start-[7px] top-1 h-2 w-2 rounded-full bg-oe-blue" />
                <div className="flex flex-wrap items-center gap-1.5">
                  <span
                    className={clsx(
                      'inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide',
                      chipStyle,
                    )}
                  >
                    {actionLabel}
                  </span>
                  <DateDisplay
                    value={ev.created_at}
                    format="relative"
                    className="text-2xs text-content-quaternary"
                  />
                </div>
                {summary && (
                  <p className="mt-0.5 text-[11px] text-content-secondary break-words">
                    {summary}
                  </p>
                )}
                {ev.user_id && (
                  <p
                    className="mt-0.5 text-[10px] font-mono text-content-quaternary truncate"
                    title={ev.user_id}
                  >
                    {ev.user_id}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

/* ── Version history timeline ──────────────────────────────────────────
   Backend endpoint: GET /v1/file-versions/?file_id=&kind=. Returns the
   full chain newest-first. Each row exposes a Download (when the chain
   item carries an addressable URL — the chain doesn't currently carry
   ``download_url``, so the button degrades to "Current" for the live
   row and is hidden on superseded rows we can't address) plus a Restore
   button that calls ``POST /v1/file-versions/{id}/restore/``.

   Gracefully renders null on 404 / error so older backends that
   haven't run the file-versions migration can't break the preview
   pane. */
function VersionHistorySection({
  fileId,
  kind,
}: {
  fileId: string;
  kind: FileKind;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const { data: versions, isLoading, isError } = useFileVersions(fileId, kind);
  const restore = useRestoreVersion(fileId, kind);
  const [pendingId, setPendingId] = useState<string | null>(null);

  if (isError) return null;
  const rows = versions ?? [];
  if (!isLoading && rows.length === 0) return null;

  const handleRestore = (v: FileVersionResponse) => {
    if (restore.isPending) return;
    setPendingId(v.id);
    restore.mutate(v.id, {
      onSuccess: (restored) => {
        addToast({
          type: 'success',
          title: t('files.versions.restored_title', {
            defaultValue: 'Restored to V{{n}}',
            n: String(restored.version_number).padStart(2, '0'),
          }),
        });
        setPendingId(null);
      },
      onError: (err: Error) => {
        addToast({
          type: 'error',
          title: t('files.versions.restore_failed', {
            defaultValue: 'Could not restore version',
          }),
          message: err.message,
        });
        setPendingId(null);
      },
    });
  };

  return (
    <div className="border-t border-border-light pt-3 mt-3">
      <h4 className="flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-2">
        <History size={11} strokeWidth={2} />
        {t('files.versions.section_label', { defaultValue: 'Versions' })}
        {rows.length > 0 && (
          <span className="ms-1 text-content-quaternary tabular-nums">({rows.length})</span>
        )}
      </h4>
      {isLoading ? (
        <div className="h-3 rounded bg-surface-secondary animate-pulse" />
      ) : (
        <ol className="space-y-1.5" data-testid="version-history-list">
          {rows.map((v) => (
            <li
              key={v.id}
              data-testid={`version-history-row-${v.version_number}`}
              className={clsx(
                'flex items-start gap-2 rounded-md border px-2 py-1.5',
                v.is_current
                  ? 'border-oe-blue/30 bg-oe-blue/5'
                  : 'border-border-light bg-surface-elevated',
              )}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <VersionBadge
                    versionNumber={v.version_number}
                    isCurrent={v.is_current}
                  />
                  <DateDisplay
                    value={v.uploaded_at}
                    format="datetime"
                    className="text-[10px] text-content-tertiary"
                  />
                </div>
                {v.notes && (
                  <p className="mt-0.5 text-[11px] text-content-secondary line-clamp-2">
                    {v.notes}
                  </p>
                )}
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                {v.is_current ? (
                  <span className="text-[10px] font-medium text-oe-blue uppercase tracking-wide">
                    {t('files.versions.current', { defaultValue: 'Current' })}
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => handleRestore(v)}
                    disabled={restore.isPending}
                    data-testid={`version-history-restore-${v.version_number}`}
                    className={clsx(
                      'inline-flex items-center gap-1 h-6 px-1.5 rounded text-[10px] font-medium',
                      'text-oe-blue hover:bg-oe-blue/10',
                      'disabled:opacity-50 disabled:cursor-not-allowed',
                    )}
                    title={t('files.versions.make_current_title', {
                      defaultValue: 'Promote this version to current',
                    })}
                  >
                    {pendingId === v.id ? (
                      <Loader2 size={10} className="animate-spin" />
                    ) : (
                      <RotateCcw size={10} />
                    )}
                    {t('files.versions.make_current', { defaultValue: 'Make current' })}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/* ── CDE lifecycle status control ──────────────────────────────────────
   A compact dropdown that promotes / demotes a document's ISO 19650 CDE
   state (WIP → Shared → Published → Archived). Backed by
   PATCH /v1/documents/{id} with a ``cde_state`` body. Optimism is handled
   by the hook's query invalidation: once the patch lands, the file list +
   tree refetch and every badge re-renders with the new value. While the
   request is in flight we render a spinner and disable the trigger. */
const CDE_ORDER: CdeState[] = ['wip', 'shared', 'published', 'archived'];

// Map a raw backend error message for a blocked ISO 19650 CDE transition onto
// a clear, translatable i18n key. The Documents PATCH path enforces the
// forward-only lifecycle plus role / signature / suitability gates, and a
// rejected promotion comes back as an English ``detail`` string
// ("Invalid CDE state transition: ...", "Insufficient role: ...",
// "Gate B (SHARED -> PUBLISHED) requires approver_signature",
// "Suitability code 'A1' is not allowed in state 'shared' ..."). Rather than
// dump that raw text in a toast, classify it so the user sees a localized,
// actionable message. Returns ``null`` when the error is not a known
// CDE-transition error so the caller can fall back to the generic message.
function cdeTransitionErrorKey(message: string): string | null {
  const m = message.toLowerCase();
  if (m.includes('not allowed in state') || m.includes('suitability code')) {
    return 'files.status.error_suitability_invalid';
  }
  if (m.includes('requires approver_signature') || m.includes('approver signature')) {
    return 'files.status.error_signature_required';
  }
  if (m.includes('insufficient role') || m.includes('cannot pass gate')) {
    return 'files.status.error_role_denied';
  }
  if (m.includes('invalid cde state transition') || m.includes('is not allowed. allowed')) {
    return 'files.status.error_transition_blocked';
  }
  return null;
}

// English fallbacks for the classified CDE-transition error messages. Kept
// alongside the classifier so the control is self-contained; the keys are also
// in the locale files for translation into every shipped language.
const CDE_ERROR_FALLBACK: Record<string, string> = {
  'files.status.error_transition_blocked':
    'This is not a valid ISO 19650 transition. Documents move forward only: WIP to Shared to Published to Archived, and Archived is final.',
  'files.status.error_role_denied':
    'Your role cannot make this transition. Sharing needs a task team manager, publishing needs a lead appointed party, and archiving needs an administrator.',
  'files.status.error_signature_required':
    'Publishing a document requires an approver signature.',
  'files.status.error_suitability_invalid':
    'That suitability code is not valid for this state. ISO 19650 codes are state-scoped: S0 in WIP, S1 to S7 in Shared, A1 to A5 in Published, AR in Archived.',
};

function CdeStatusControl({
  projectId,
  documentId,
  current,
}: {
  projectId: string;
  documentId: string;
  current: string | null;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const setState = useSetDocumentCdeState(projectId);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const activeKey = current && CDE_BADGE[current] ? current : null;
  const activeCfg = activeKey ? CDE_BADGE[activeKey] : null;

  const handlePick = (next: CdeState) => {
    setOpen(false);
    if (next === current) return;
    setState.mutate(
      { documentId, cdeState: next },
      {
        onSuccess: () => {
          addToast({
            type: 'success',
            title: t('files.status.changed', {
              defaultValue: 'Status set to {{state}}',
              state: t(`files.status.state.${next}`, {
                defaultValue: CDE_BADGE[next]?.label ?? next,
              }),
            }),
          });
        },
        onError: (err: unknown) => {
          // A rejected ISO 19650 CDE state change (forward-only lifecycle,
          // role gate, signature gate, or out-of-state suitability code) comes
          // back as a 400 with an English detail string. Classify it so the
          // user sees a clear, localized reason instead of the raw backend
          // text; fall back to the generic toast for anything else.
          const raw = err instanceof Error ? err.message : String(err);
          const key = cdeTransitionErrorKey(raw);
          if (key) {
            addToast({
              type: 'error',
              title: t('files.status.transition_not_allowed', {
                defaultValue: 'Transition not allowed',
              }),
              message: t(key, { defaultValue: CDE_ERROR_FALLBACK[key] ?? raw }),
            });
            return;
          }
          addToast({
            type: 'error',
            title: t('files.status.change_failed', {
              defaultValue: 'Could not change status',
            }),
            message: raw,
          });
        },
      },
    );
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        disabled={setState.isPending}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={clsx(
          'inline-flex items-center gap-1.5 h-6 px-1.5 rounded-md text-[10px] font-medium transition-colors',
          'border border-border-light hover:border-oe-blue/40 hover:bg-surface-secondary',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
          'disabled:opacity-60 disabled:cursor-wait',
        )}
        title={t('files.status.set_hint', {
          defaultValue: 'Set the CDE lifecycle status',
        })}
      >
        {setState.isPending ? (
          <Loader2 size={11} className="animate-spin" />
        ) : activeCfg ? (
          <span
            className={clsx(
              'inline-flex items-center rounded px-1 py-px text-[9px] font-medium uppercase tracking-wider',
              activeCfg.cls,
            )}
          >
            {activeCfg.label}
          </span>
        ) : (
          <span className="text-content-tertiary uppercase tracking-wider">
            {t('files.status.unset', { defaultValue: 'Set status' })}
          </span>
        )}
        <ChevronDown size={11} className={clsx('transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute right-0 top-full mt-1 w-40 rounded-lg border border-border-light bg-surface-elevated shadow-lg z-20 overflow-hidden"
        >
          {CDE_ORDER.map((key) => {
            const cfg = CDE_BADGE[key]!;
            const isActive = key === current;
            // ISO 19650 is forward-only: WIP -> Shared -> Published ->
            // Archived. A null/unset state is treated as WIP. Only the current
            // state or the immediate next one is selectable; backward and
            // skip-ahead options are disabled so the UI mirrors the backend
            // lifecycle and never offers a guaranteed-reject transition.
            const curIdx = CDE_ORDER.indexOf((current as CdeState) ?? 'wip');
            const keyIdx = CDE_ORDER.indexOf(key);
            const selectable = keyIdx === curIdx || keyIdx === curIdx + 1;
            return (
              <button
                key={key}
                type="button"
                role="option"
                aria-selected={isActive}
                disabled={!selectable}
                title={
                  selectable
                    ? undefined
                    : t('files.status.forward_only_hint', {
                        defaultValue:
                          'Documents move forward only: WIP to Shared to Published to Archived.',
                      })
                }
                onClick={() => selectable && handlePick(key)}
                className={clsx(
                  'flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-[11px] transition-colors',
                  isActive
                    ? 'bg-oe-blue/10 text-oe-blue font-medium'
                    : selectable
                      ? 'text-content-secondary hover:bg-surface-secondary'
                      : 'text-content-quaternary opacity-50 cursor-not-allowed',
                )}
              >
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className={clsx(
                      'inline-flex items-center rounded px-1 py-px text-[9px] font-medium uppercase tracking-wider',
                      cfg.cls,
                    )}
                  >
                    {cfg.label}
                  </span>
                  {t(`files.status.state.${key}`, { defaultValue: cfg.label })}
                </span>
                {isActive && <Check size={12} className="shrink-0" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[10px] uppercase tracking-wider text-content-quaternary">{label}</dt>
      <dd className="text-content-primary">{children}</dd>
    </div>
  );
}
