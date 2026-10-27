// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Image types the server accepts for a profile photo. */
export const AVATAR_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const;

/** Mirrors the server cap (`MAX_AVATAR_BYTES`). */
export const AVATAR_MAX_BYTES = 2 * 1024 * 1024;

export type AvatarErrorKey =
  | 'settings.avatar_err_type'
  | 'settings.avatar_err_size'
  | 'settings.avatar_err_content';

/** Why a chosen file cannot be a profile photo, or `null` when it can. */
export function validateAvatarFile(file: Pick<File, 'type' | 'size'>): AvatarErrorKey | null {
  if (!(AVATAR_TYPES as readonly string[]).includes(file.type)) return 'settings.avatar_err_type';
  if (file.size > AVATAR_MAX_BYTES || file.size === 0) {
    return file.size === 0 ? 'settings.avatar_err_content' : 'settings.avatar_err_size';
  }
  return null;
}

/** Maps the server's rule id (`detail.rule` of a 422) to a message key. */
export function avatarErrorKeyForRule(rule: string | undefined): AvatarErrorKey {
  if (rule === 'users.avatar.type') return 'settings.avatar_err_type';
  if (rule === 'users.avatar.size') return 'settings.avatar_err_size';
  return 'settings.avatar_err_content';
}
