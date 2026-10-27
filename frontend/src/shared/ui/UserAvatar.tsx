// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ReactNode } from 'react';
import { AuthImage } from './AuthImage';

export interface UserAvatarProps {
  /** API path of the profile photo (`avatar_url` from `/v1/users/me/`), if any. */
  src?: string | null;
  /** Shown when there is no photo or it cannot be loaded. */
  initials: ReactNode;
  /** Accessible name of the photo; the initials fallback is decorative. */
  alt?: string;
  /** Classes for the photo, sized to fill the parent. */
  imgClassName?: string;
}

/**
 * The profile photo, or the initials the caller passes when there is none.
 *
 * The parent owns the shape and size (a rounded box with overflow hidden);
 * this only fills it. A photo that fails to load falls back to the initials.
 */
export function UserAvatar({ src, initials, alt = '', imgClassName = '' }: UserAvatarProps) {
  if (!src) return <>{initials}</>;
  return (
    <AuthImage
      src={src}
      alt={alt}
      className={`h-full w-full object-cover ${imgClassName}`.trim()}
      placeholder={<>{initials}</>}
      fallback={<>{initials}</>}
    />
  );
}
