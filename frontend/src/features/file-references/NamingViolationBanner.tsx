// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Top-of-preview banner listing ISO 19650 naming violations for the
 * currently-selected file.
 *
 * Looks up the violation row via the project-wide ``GET /violations/``
 * query (cached for 30s by ``useViolations``) — there is no per-file
 * GET so the banner can render before the project scan completes
 * without flicker on every preview switch.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Button } from '@/shared/ui/Button';
import { useToastStore } from '@/stores/useToastStore';
import { fileReferenceKeys } from './api';
import { IsoNameBuilder } from './IsoNameBuilder';
import { useAcknowledgeViolation, useValidateName, useViolations } from './hooks';
import type {
  FileKind,
  Iso19650Parts,
  NamingViolationResponse,
  ViolationCode,
} from './types';

export interface NamingViolationBannerProps {
  projectId: string;
  fileKind: FileKind;
  fileId: string;
  /**
   * Rename the file to `nextFilename`. Supplying this is what turns the
   * banner from a notice into something a user can act on.
   *
   * The banner deliberately does not reach for a rename endpoint itself.
   * Only documents are backed by a table that owns a `name` column, and the
   * banner is rendered over eight file kinds, so the host decides whether a
   * rename is possible here and passes the callback only when it is. Without
   * it the fix button is absent rather than present and failing.
   */
  onRename?: (nextFilename: string) => Promise<unknown>;
  className?: string;
}

/** All nine fields blank, for when the pre-fill call could not be made. */
const EMPTY_PARTS: Iso19650Parts = {
  project: null,
  originator: null,
  volume: null,
  level: null,
  type: null,
  role: null,
  number: null,
  status: null,
  revision: null,
};

/** Trailing extension of a filename, without the dot. Null when there is none. */
function extensionOf(filename: string): string | null {
  const dot = filename.lastIndexOf('.');
  if (dot <= 0 || dot === filename.length - 1) return null;
  return filename.slice(dot + 1);
}

const CODE_LABELS: Record<ViolationCode, string> = {
  'not-iso19650': 'Name does not match ISO 19650 format',
  'missing-volume': 'Volume field is missing',
  'bad-level': 'Level field must be 2 characters',
  'bad-role-code': 'Role code must be 2-4 characters',
  'bad-number': 'Number must be exactly 4 digits',
  'too-many-parts': 'Too many hyphen-separated parts',
  'too-few-parts': 'Too few hyphen-separated parts (need at least 7)',
};

const CODE_RULE_REFS: Record<ViolationCode, string> = {
  'not-iso19650': 'ISO 19650-2 §5.4 - File naming convention',
  'missing-volume': 'ISO 19650-2 §5.4.2 - Volume / System',
  'bad-level': 'ISO 19650-2 §5.4.2 - Level / Location',
  'bad-role-code': 'ISO 19650-2 §5.4.2 - Role (discipline)',
  'bad-number': 'ISO 19650-2 §5.4.2 - Number (4-digit sequence)',
  'too-many-parts': 'ISO 19650-2 §5.4 - Maximum 9 fields',
  'too-few-parts': 'ISO 19650-2 §5.4 - Minimum 7 required fields',
};

export function NamingViolationBanner({
  projectId,
  fileKind,
  fileId,
  onRename,
  className,
}: NamingViolationBannerProps) {
  const { t } = useTranslation();
  const [showDetail, setShowDetail] = useState(false);
  const [builderParts, setBuilderParts] = useState<Iso19650Parts | null>(null);
  const [renaming, setRenaming] = useState(false);
  const addToast = useToastStore((s) => s.addToast);
  const qc = useQueryClient();
  const { data, isLoading } = useViolations({
    projectId,
    includeAcknowledged: false,
    limit: 500,
  });
  const ackMut = useAcknowledgeViolation(projectId);
  const validateMut = useValidateName();

  const violation = useMemo<NamingViolationResponse | null>(() => {
    if (!data) return null;
    return (
      data.items.find(
        (v) => v.file_kind === fileKind && v.file_id === fileId,
      ) ?? null
    );
  }, [data, fileKind, fileId]);

  if (isLoading || violation === null) return null;

  const codes = violation.violation_codes;
  const currentName = violation.filename;

  /* Fill the wizard from the name that failed. The validator returns its
     field split even when the overall name is invalid, which is the whole
     point: a user correcting one wrong field should not have to retype the
     eight that were already right. */
  const openBuilder = () => {
    validateMut.mutate(
      { filename: currentName },
      {
        onSuccess: (res) => setBuilderParts(res.parts),
        onError: () => {
          // An empty wizard is still a way to fix the name. Refusing to open
          // it because the pre-fill call failed would put the user back where
          // this banner started, with nothing to do but dismiss the warning.
          setBuilderParts(EMPTY_PARTS);
        },
      },
    );
  };

  const applyName = async (nextFilename: string) => {
    if (!onRename) return;
    setRenaming(true);
    try {
      await onRename(nextFilename);
      setBuilderParts(null);
      // The violation row is keyed on the old name, so the banner has to be
      // re-read rather than left showing a complaint about a name that is gone.
      qc.invalidateQueries({
        queryKey: [fileReferenceKeys.violations, projectId],
      });
      addToast({
        type: 'success',
        title: t('files.naming.renamed_toast', { defaultValue: 'File renamed' }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('files.naming.rename_failed', {
          defaultValue: 'Could not rename the file',
        }),
        message: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setRenaming(false);
    }
  };

  return (
    <div
      className={clsx(
        'rounded-lg border border-semantic-warning/40 bg-semantic-warning/10 p-3 text-sm',
        className,
      )}
      role="alert"
      aria-live="polite"
      data-testid="naming-violation-banner"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-semantic-warning/30 text-semantic-warning">
          <span aria-hidden="true">!</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-medium text-content-primary">
            {t('files.naming.banner_title', {
              defaultValue: 'Filename does not match the project naming rules',
            })}
          </div>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-content-secondary">
            {codes.map((c) => (
              <li key={c} data-testid={`violation-code-${c}`}>
                {t(`files.naming.code.${c}`, {
                  defaultValue: CODE_LABELS[c] ?? c,
                })}
              </li>
            ))}
          </ul>
          {showDetail && (
            <div className="mt-2 rounded border border-border bg-surface-primary p-2 text-xs">
              <div className="mb-1 font-medium text-content-primary">
                {t('files.naming.rule_set', {
                  defaultValue: 'Rule set: {{rs}}',
                  rs: violation.rule_set,
                })}
              </div>
              <ul className="space-y-1 text-content-secondary">
                {codes.map((c) => (
                  <li key={c}>
                    <span className="font-mono">{c}</span> —{' '}
                    {CODE_RULE_REFS[c] ?? '—'}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {builderParts !== null && (
            <div className="mt-3" data-testid="violation-name-builder">
              <IsoNameBuilder
                initialParts={builderParts}
                extension={extensionOf(currentName)}
                onApply={applyName}
                onCancel={() => setBuilderParts(null)}
              />
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-col gap-1">
          {/* The fix comes before the dismissal, deliberately. Until this
              button existed the only two actions were to read the rule and to
              acknowledge the violation, so the banner's own affordance pushed
              a user towards suppressing the warning rather than correcting
              the name it was about. */}
          {onRename && (
            <Button
              variant="primary"
              size="sm"
              onClick={openBuilder}
              loading={validateMut.isPending || renaming}
              data-testid="violation-fix-name"
              type="button"
            >
              {t('files.naming.fix_name', { defaultValue: 'Fix name' })}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowDetail((s) => !s)}
            data-testid="violation-toggle-rule"
            type="button"
          >
            {showDetail
              ? t('files.naming.hide_rule', { defaultValue: 'Hide rule' })
              : t('files.naming.show_rule', { defaultValue: 'Show rule' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              ackMut.mutate(violation.id, {
                onSuccess: () => {
                  addToast({
                    type: 'success',
                    title: t('files.naming.acknowledged_toast', {
                      defaultValue: 'Violation acknowledged',
                    }),
                  });
                },
                onError: (err) => {
                  addToast({
                    type: 'error',
                    title: t('files.naming.acknowledge_failed', {
                      defaultValue: 'Could not acknowledge',
                    }),
                    message: err instanceof Error ? err.message : undefined,
                  });
                },
              });
            }}
            loading={ackMut.isPending}
            data-testid="violation-acknowledge"
            type="button"
          >
            {t('files.naming.acknowledge', { defaultValue: 'Acknowledge' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
