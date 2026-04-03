/**
 * Presence tracking for BOQ collaboration.
 *
 * Tracks which users are viewing/editing which BOQs.
 * In demo mode, generates mock presence data.
 * When a real WebSocket/WebRTC backend is available,
 * this hook will use the Yjs awareness protocol instead.
 */
import { create } from 'zustand';

export interface PresenceUser {
  id: string;
  name: string;
  email: string;
  color: string;
  /** Which BOQ the user is currently viewing */
  boqId: string | null;
  /** Which field they're editing (if any) */
  activeField?: string;
  /** Timestamp of last activity */
  lastSeen: number;
}

interface PresenceState {
  /** Remote users currently online (keyed by user ID) */
  remoteUsers: Record<string, PresenceUser>;
  /** Set presence for a remote user */
  setUserPresence: (user: PresenceUser) => void;
  /** Remove user (went offline) */
  removeUser: (userId: string) => void;
  /** Get all users currently viewing a specific BOQ */
  getUsersForBOQ: (boqId: string) => PresenceUser[];
  /** Seed demo presence data */
  seedDemoPresence: (boqIds: string[]) => void;
  /** Clear all presence data */
  clearPresence: () => void;
}

const DEMO_USERS: Omit<PresenceUser, 'boqId' | 'lastSeen'>[] = [
  { id: 'demo-1', name: 'Sarah K.', email: 'sarah@example.com', color: '#3b82f6' },
  { id: 'demo-2', name: 'Max M.', email: 'max@example.com', color: '#10b981' },
  { id: 'demo-3', name: 'Lena B.', email: 'lena@example.com', color: '#f59e0b' },
];

export const usePresenceStore = create<PresenceState>((set, get) => ({
  remoteUsers: {},

  setUserPresence: (user) =>
    set((state) => ({
      remoteUsers: { ...state.remoteUsers, [user.id]: user },
    })),

  removeUser: (userId) =>
    set((state) => {
      const { [userId]: _, ...rest } = state.remoteUsers;
      return { remoteUsers: rest };
    }),

  getUsersForBOQ: (boqId) =>
    Object.values(get().remoteUsers).filter((u) => u.boqId === boqId),

  seedDemoPresence: (boqIds) => {
    if (boqIds.length === 0) return;
    const users: Record<string, PresenceUser> = {};
    // Assign 1-2 demo users to random BOQs
    const count = Math.min(DEMO_USERS.length, Math.max(1, Math.floor(boqIds.length * 0.4)));
    for (let i = 0; i < count; i++) {
      const user = DEMO_USERS[i]!;
      const boqId = boqIds[i % boqIds.length] ?? '';
      users[user.id] = {
        ...user,
        boqId,
        lastSeen: Date.now(),
      };
    }
    set({ remoteUsers: users });
  },

  clearPresence: () => set({ remoteUsers: {} }),
}));
