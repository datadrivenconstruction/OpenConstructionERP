// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FieldImageToggle - mark an arbitrary image document as field/site imagery.
 *
 * Background (#284 follow-up): the project "Photo strip" shows site
 * documentation only. A dedicated ``ProjectPhoto`` is always field; a
 * general ``Document`` is field ONLY when it carries an explicit ``field``
 * tag. This control toggles that tag on a document via the existing
 * ``PATCH /v1/documents/{id}`` ``tags`` affordance (no schema change), so:
 *   - a site image uploaded into Project Files can be SHOWN in the strip, and
 *   - an office render can be kept OUT of it.
 *
 * The component is intentionally self-contained (it owns its PATCH + cache
 * invalidation) so any surface that lists documents - the file manager, a
 * project image grid - can drop it next to an image without new plumbing.
 *
 * Canonical contract (shared across groups): the "field vs general" signal is
 * ``ProjectPhoto.category`` (site*) OR ``Document.category === 'photo'`` OR a
 * ``field`` tag on the document. This toggle owns the last of those.
 */
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { MapPin, Loader2 } from 'lucide-react';
import { apiPatch } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

/** The shared tag that opts a general image INTO the site Photo strip. */
export const FIELD_TAG = 'field';

/** True when a document's tag list already marks it as field/site imagery. */
export function hasFieldTag(tags: string[] | null | undefined): boolean {
  return (tags ?? []).some((t) => t.toLowerCase() === FIELD_TAG);
}

interface FieldImageToggleProps {
  /** Document id to PATCH. */
  documentId: string;
  /** Current tags on the document (used to compute the next tag list). */
  tags: string[] | null | undefined;
  /** Render compactly (icon-only chip) for dense grids. */
  compact?: boolean;
  /** Disable interaction (e.g. caller lacks edit rights). */
  disabled?: boolean;
  /** Invoked with the next tag list after a successful PATCH. */
  onChanged?: (nextTags: string[]) => void;
  className?: string;
}

/**
 * Compute the next tag list when toggling the ``field`` tag. Pure - exported
 * for unit testing without rendering or a live backend.
 */
export function nextFieldTags(
  tags: string[] | null | undefined,
  makeField: boolean,
): string[] {
  const current = tags ?? [];
  if (makeField) {
    return hasFieldTag(current) ? [...current] : [...current, FIELD_TAG];
  }
  // Drop every case-variant of the field tag.
  return current.filter((t) => t.toLowerCase() !== FIELD_TAG);
}

export function FieldImageToggle({
  documentId,
  tags,
  compact = false,
  disabled = false,
  onChanged,
  className,
}: FieldImageToggleProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  const isField = useMemo(() => hasFieldTag(tags), [tags]);

  const toggle = useCallback(async () => {
    if (busy || disabled) return;
    const next = nextFieldTags(tags, !isField);
    setBusy(true);
    try {
      await apiPatch<unknown>(`/v1/documents/${documentId}`, { tags: next });
      // Refresh any list that may show this document or the strip.
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['proj-widget-photo-docs'] }),
        qc.invalidateQueries({ queryKey: ['documents'] }),
      ]);
      onChanged?.(next);
      addToast({
        type: 'success',
        title: '',
        message: isField
          ? t('documents.field_removed', { defaultValue: 'Removed from site photos' })
          : t('documents.field_added', { defaultValue: 'Marked as a site photo' }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message:
          err instanceof Error
            ? err.message
            : t('documents.field_toggle_failed', {
                defaultValue: 'Could not update the image tag.',
              }),
      });
    } finally {
      setBusy(false);
    }
  }, [busy, disabled, tags, isField, documentId, qc, onChanged, addToast, t]);

  const label = isField
    ? t('documents.field_image_on', { defaultValue: 'Site photo' })
    : t('documents.field_image_off', { defaultValue: 'Mark as site photo' });

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={disabled || busy}
      aria-pressed={isField}
      title={t('documents.field_image_hint', {
        defaultValue: 'Show this image in the project Photo strip (field/site evidence).',
      })}
      className={[
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium transition-colors disabled:opacity-50',
        isField
          ? 'border-oe-blue/40 bg-oe-blue-subtle/30 text-oe-blue-text'
          : 'border-dashed border-border-light text-content-tertiary hover:border-oe-blue/40 hover:text-oe-blue',
        className ?? '',
      ].join(' ')}
    >
      {busy ? <Loader2 size={11} className="animate-spin" /> : <MapPin size={11} />}
      {!compact && label}
    </button>
  );
}
