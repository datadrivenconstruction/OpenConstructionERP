// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Camera, Trash2, Upload } from 'lucide-react';
import { API_BASE, apiDelete, fetchWithAuth } from '@/shared/lib/api';
import { Button } from '@/shared/ui';
import { UserAvatar } from '@/shared/ui/UserAvatar';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { AVATAR_TYPES, avatarErrorKeyForRule, validateAvatarFile } from './avatarFile';
import type { AvatarErrorKey } from './avatarFile';

interface AvatarEditorProps {
  name: string | undefined;
  avatarUrl: string | null | undefined;
}

class AvatarUploadError extends Error {
  constructor(public readonly key: AvatarErrorKey | null, message: string) {
    super(message);
  }
}

async function uploadAvatar(file: File): Promise<void> {
  const body = new FormData();
  body.append('file', file);
  const res = await fetchWithAuth(`${API_BASE}/v1/users/me/avatar/`, { method: 'POST', body });
  if (res.ok) return;
  let rule: string | undefined;
  try {
    const json = (await res.json()) as { detail?: { rule?: string } | string };
    if (json.detail && typeof json.detail === 'object') rule = json.detail.rule;
  } catch {
    /* not JSON: fall through to the generic message */
  }
  throw new AvatarUploadError(res.status === 422 ? avatarErrorKeyForRule(rule) : null, `HTTP ${res.status}`);
}

/**
 * Profile photo with an initials fallback. Choosing a file shows it in the
 * same frame first (the server crops a centred square, so the preview uses the
 * same crop); nothing is sent until the user confirms.
 */
export function AvatarEditor({ name, avatarUrl }: AvatarEditorProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const inputRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<AvatarErrorKey | null>(null);

  useEffect(() => {
    if (!pending) {
      setPreviewUrl(null);
      return undefined;
    }
    const url = URL.createObjectURL(pending);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [pending]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['me'] });
    void useAuthStore.getState().syncRoleFromServer();
  };

  const upload = useMutation({
    mutationFn: uploadAvatar,
    onSuccess: () => {
      setPending(null);
      setError(null);
      refresh();
      addToast({ type: 'success', title: t('settings.avatar_saved', { defaultValue: 'Profile photo updated' }) });
    },
    onError: (err: Error) => {
      const key = err instanceof AvatarUploadError ? err.key : null;
      if (key) setError(key);
      addToast({
        type: 'error',
        title: t('settings.avatar_failed', { defaultValue: 'Could not save the photo' }),
        message: key ? undefined : err.message,
      });
    },
  });

  const remove = useMutation({
    mutationFn: () => apiDelete('/v1/users/me/avatar/'),
    onSuccess: () => {
      setPending(null);
      setError(null);
      refresh();
      addToast({ type: 'success', title: t('settings.avatar_removed', { defaultValue: 'Profile photo removed' }) });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    const problem = validateAvatarFile(file);
    if (problem) {
      setPending(null);
      setError(problem);
      return;
    }
    setError(null);
    setPending(file);
  };

  const initials = (
    <span aria-hidden="true">{name?.charAt(0)?.toUpperCase() || 'U'}</span>
  );
  const hasPhoto = !!avatarUrl;
  const busy = upload.isPending || remove.isPending;
  const alt = t('settings.avatar_alt', { defaultValue: 'Your profile photo' });

  return (
    <div className="flex shrink-0 flex-col items-center gap-2 sm:items-start">
      <div
        className="flex h-20 w-20 items-center justify-center overflow-hidden rounded-2xl bg-gradient-to-br from-oe-blue to-oe-blue-hover text-3xl font-bold text-oe-on-accent shadow-sm"
        data-testid="avatar-frame"
      >
        {previewUrl ? (
          <img src={previewUrl} alt={alt} className="h-full w-full object-cover" data-testid="avatar-preview" />
        ) : (
          <UserAvatar src={avatarUrl} initials={initials} alt={alt} />
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept={AVATAR_TYPES.join(',')}
        className="hidden"
        onChange={onPick}
        data-testid="avatar-input"
        aria-label={t('settings.avatar_upload', { defaultValue: 'Upload photo' })}
      />

      {pending ? (
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" onClick={() => upload.mutate(pending)} loading={upload.isPending} disabled={busy}>
            {t('settings.avatar_save', { defaultValue: 'Save photo' })}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setPending(null)} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          <Button
            size="sm"
            variant="secondary"
            icon={hasPhoto ? <Camera size={14} /> : <Upload size={14} />}
            onClick={() => inputRef.current?.click()}
            disabled={busy}
          >
            {hasPhoto
              ? t('settings.avatar_change', { defaultValue: 'Change photo' })
              : t('settings.avatar_upload', { defaultValue: 'Upload photo' })}
          </Button>
          {hasPhoto && (
            <Button
              size="sm"
              variant="ghost"
              icon={<Trash2 size={14} />}
              onClick={() => remove.mutate()}
              loading={remove.isPending}
              disabled={busy}
            >
              {t('settings.avatar_remove', { defaultValue: 'Remove photo' })}
            </Button>
          )}
        </div>
      )}

      <p className="max-w-[11rem] text-2xs text-content-tertiary">
        {t('settings.avatar_hint', { defaultValue: 'PNG, JPEG or WebP, up to 2 MB. Cropped to a square.' })}
      </p>
      {error && (
        <p role="alert" className="max-w-[11rem] text-2xs text-semantic-error">
          {t(error, {
            defaultValue:
              error === 'settings.avatar_err_type'
                ? 'Choose a PNG, JPEG or WebP image.'
                : error === 'settings.avatar_err_size'
                  ? 'The photo is larger than 2 MB.'
                  : 'That file is not a readable image.',
          })}
        </p>
      )}
    </div>
  );
}
