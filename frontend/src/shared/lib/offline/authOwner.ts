import { useAuthStore } from '@/stores/useAuthStore';
import type { QueueOwner } from './mutationQueue';

/** The signed-in office user, for queues replayed with the account token. */
export function authOwner(): QueueOwner | null {
  const { isAuthenticated, userId, userEmail } = useAuthStore.getState();
  return isAuthenticated && userId ? { userId, label: userEmail } : null;
}
