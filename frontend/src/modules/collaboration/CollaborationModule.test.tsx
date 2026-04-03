// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import CollaborationModule from './CollaborationModule';
import { COLLAB_COLORS, pickColor } from './types';
import { ConnectionStatus } from './components/ConnectionStatus';
import { CollaborationBar } from './components/CollaborationBar';
import type { ConnectionStatusInfo } from './hooks/useConnectionStatus';
import type { CollabUser } from './types';

describe('CollaborationModule', () => {
  it('should render the page header', () => {
    render(<CollaborationModule />);
    expect(screen.getByText('Real-time Collaboration')).toBeInTheDocument();
    expect(screen.getByText(/Work together on estimates/)).toBeInTheDocument();
  });

  it('should render feature cards', () => {
    render(<CollaborationModule />);
    expect(screen.getByText('Peer-to-Peer Sync')).toBeInTheDocument();
    expect(screen.getByText('CRDT Conflict Resolution')).toBeInTheDocument();
    expect(screen.getByText('Presence Awareness')).toBeInTheDocument();
  });

  it('should render display name input', () => {
    render(<CollaborationModule />);
    expect(screen.getByText('Your display name')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Your name')).toBeInTheDocument();
  });

  it('should save display name to localStorage', () => {
    render(<CollaborationModule />);
    const input = screen.getByPlaceholderText('Your name');
    fireEvent.change(input, { target: { value: 'Test User' } });
    fireEvent.click(screen.getByText('Save'));
    expect(localStorage.getItem('oe_collab_name')).toBe('Test User');
  });

  it('should show color palette', () => {
    render(<CollaborationModule />);
    expect(screen.getByText('User Colors')).toBeInTheDocument();
  });

  it('should show how-to steps', () => {
    render(<CollaborationModule />);
    expect(screen.getByText(/Open a BOQ in the editor/)).toBeInTheDocument();
    expect(screen.getByText(/Click "Share"/)).toBeInTheDocument();
    expect(screen.getByText(/Send the link/)).toBeInTheDocument();
    expect(screen.getByText(/Edit together/)).toBeInTheDocument();
  });

  it('should show disclaimer', () => {
    render(<CollaborationModule />);
    expect(screen.getByText(/peer-to-peer WebRTC/)).toBeInTheDocument();
  });
});

describe('Collaboration types', () => {
  it('should have 8 predefined colors', () => {
    expect(COLLAB_COLORS).toHaveLength(8);
  });

  it('should have unique colors', () => {
    expect(new Set(COLLAB_COLORS).size).toBe(COLLAB_COLORS.length);
  });

  it('pickColor should cycle through colors', () => {
    expect(pickColor(0)).toBe(COLLAB_COLORS[0]);
    expect(pickColor(7)).toBe(COLLAB_COLORS[7]);
    expect(pickColor(8)).toBe(COLLAB_COLORS[0]); // wraps around
    expect(pickColor(15)).toBe(COLLAB_COLORS[7]);
  });
});

describe('Collaboration module registration', () => {
  it('should be registered in MODULE_REGISTRY', async () => {
    const { MODULE_REGISTRY } = await import('../_registry');
    const mod = MODULE_REGISTRY.find((m) => m.id === 'collaboration');
    expect(mod).toBeDefined();
    expect(mod!.name).toBe('Real-time Collaboration');
    expect(mod!.routes[0].path).toBe('/collaboration');
  }, 15000);
});

// --- ConnectionStatus component tests ---

describe('ConnectionStatus', () => {
  const baseInfo: ConnectionStatusInfo = {
    status: 'connected',
    peerCount: 3,
    lastSyncTime: Date.now(),
    secondsSinceSync: 2,
  };

  it('should show green dot and peer count when connected', () => {
    render(<ConnectionStatus connectionInfo={baseInfo} />);
    expect(screen.getByText('3 peers')).toBeInTheDocument();
  });

  it('should show 0 peers label when peerCount is 0', () => {
    render(
      <ConnectionStatus connectionInfo={{ ...baseInfo, peerCount: 0 }} />,
    );
    expect(screen.getByText('0 peers')).toBeInTheDocument();
  });

  it('should show 1 peer label when peerCount is 1', () => {
    render(
      <ConnectionStatus connectionInfo={{ ...baseInfo, peerCount: 1 }} />,
    );
    expect(screen.getByText('1 peers')).toBeInTheDocument();
  });

  it('should show tooltip with full status on hover', async () => {
    render(<ConnectionStatus connectionInfo={baseInfo} />);
    // Hover over the indicator
    const container = screen.getByText('3 peers').closest('div')!;
    fireEvent.mouseEnter(container);
    // Tooltip should show "Connected" and "Synced just now"
    expect(screen.getByText('Connected')).toBeInTheDocument();
    expect(screen.getByText('Synced just now')).toBeInTheDocument();
  });

  it('should show "Connecting..." for connecting state', () => {
    render(
      <ConnectionStatus
        connectionInfo={{ ...baseInfo, status: 'connecting', peerCount: 0 }}
      />,
    );
    const container = screen.getByText('0 peers').closest('div')!;
    fireEvent.mouseEnter(container);
    expect(screen.getByText('Connecting...')).toBeInTheDocument();
  });

  it('should show "Disconnected" for disconnected state', () => {
    render(
      <ConnectionStatus
        connectionInfo={{
          ...baseInfo,
          status: 'disconnected',
          peerCount: 0,
          lastSyncTime: null,
          secondsSinceSync: null,
        }}
      />,
    );
    const container = screen.getByText('0 peers').closest('div')!;
    fireEvent.mouseEnter(container);
    expect(screen.getByText('Disconnected')).toBeInTheDocument();
  });

  it('should show seconds-ago sync label for older syncs', () => {
    render(
      <ConnectionStatus
        connectionInfo={{ ...baseInfo, secondsSinceSync: 30 }}
      />,
    );
    const container = screen.getByText('3 peers').closest('div')!;
    fireEvent.mouseEnter(container);
    expect(screen.getByText('Synced 30s ago')).toBeInTheDocument();
  });

  it('should show minutes-ago sync label for much older syncs', () => {
    render(
      <ConnectionStatus
        connectionInfo={{ ...baseInfo, secondsSinceSync: 120 }}
      />,
    );
    const container = screen.getByText('3 peers').closest('div')!;
    fireEvent.mouseEnter(container);
    expect(screen.getByText('Synced 2m ago')).toBeInTheDocument();
  });

  it('should hide tooltip on mouse leave', () => {
    vi.useFakeTimers();
    render(<ConnectionStatus connectionInfo={baseInfo} />);
    const container = screen.getByText('3 peers').closest('div')!;
    fireEvent.mouseEnter(container);
    expect(screen.getByText('Connected')).toBeInTheDocument();
    fireEvent.mouseLeave(container);
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByText('Connected')).not.toBeInTheDocument();
    vi.useRealTimers();
  });
});

// --- CollaborationBar integration tests ---

describe('CollaborationBar with ConnectionStatus', () => {
  const mockUsers: CollabUser[] = [
    { userId: '1', userName: 'Alice', color: '#3b82f6', cursor: null, isLocal: true },
    { userId: '2', userName: 'Bob', color: '#10b981', cursor: null, isLocal: false },
  ];

  const connInfo: ConnectionStatusInfo = {
    status: 'connected',
    peerCount: 1,
    lastSyncTime: Date.now(),
    secondsSinceSync: 3,
  };

  it('should render ConnectionStatus inside the bar when connectionInfo is provided', () => {
    render(
      <CollaborationBar users={mockUsers} connected={true} connectionInfo={connInfo} />,
    );
    expect(screen.getByText('1 peers')).toBeInTheDocument();
  });

  it('should fall back to legacy connected boolean when connectionInfo is not provided', () => {
    render(<CollaborationBar users={mockUsers} connected={true} />);
    // Fallback builds info from users: 1 remote user = 1 peer
    expect(screen.getByText('1 peers')).toBeInTheDocument();
  });

  it('should show disconnected state via fallback when connected=false', () => {
    render(<CollaborationBar users={[]} connected={false} />);
    // Fallback: status=disconnected, peerCount=0
    expect(screen.getByText('0 peers')).toBeInTheDocument();
  });

  it('should still show user avatars alongside the connection indicator', () => {
    render(
      <CollaborationBar users={mockUsers} connected={true} connectionInfo={connInfo} />,
    );
    // Users count label ("2 online")
    expect(screen.getByText('2 online')).toBeInTheDocument();
  });
});
