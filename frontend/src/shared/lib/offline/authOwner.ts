import { useAuthStore } from '@/stores/useAuthStore';
import type { QueueOwner } from './mutationQueue';

/** The signed-in office user, for queues replayed with the account token. */
export function authOwner(): QueueOwner | null {
  const { isAuthenticated, userId, userEmail } = useAuthStore.getState();
  return isAuthenticated && userId ? { userId, label: userEmail } : null;
}

function readOnce(read: () => string | null): string | null {
  try {
    return read();
  } catch {
    return null;
  }
}

// Read when the app loads, before any sign-in of this page load can overwrite it:
// the one person the previous build had on this device.
const priorEmail = readOnce(() => localStorage.getItem('oe_user_email'));

/** The office user who used the device before queue items were stamped. */
export function priorOfficeUser(): string | null {
  return priorEmail;
}
