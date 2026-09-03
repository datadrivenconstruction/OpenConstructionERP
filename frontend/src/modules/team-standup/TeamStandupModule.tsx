// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// The Team Standup & Delivery Board page.
//
// This component is a thin HOST: the page itself is the stress-tested
// vanilla engine ported from the approved interactive preview (see
// engine/engine.ts for why it is not rewritten in React). React owns
// the lifecycle - fetch the board, mount the engine once, poll for the
// team's changes, tear everything down on navigation - and the engine
// owns every pixel inside `.standup-root`.

import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { getErrorMessage } from '@/shared/lib/api';

import { fetchFullBoard } from './api';
import type { FullBoard } from './api';
import { localDay } from './data/board';
import { bootStandupEngine } from './engine/engine';
import type { StandupEngineHandle } from './engine/engine';
import { STANDUP_MARKUP } from './engine/markup';
import './standup.css';

/** How often the board asks "what has the rest of the team done" while
 * the page is open. The engine skips a refresh mid-interaction. */
const POLL_MS = 45_000;

const FONT_HREF =
  'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap';

export default function TeamStandupModule() {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<StandupEngineHandle | null>(null);
  const navigate = useNavigate();
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  const [board, setBoard] = useState<FullBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  // The board's own faces; loaded once, removed with the page. A LAN or
  // offline install just falls back to the system stack in the CSS.
  useEffect(() => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = FONT_HREF;
    document.head.appendChild(link);
    return () => {
      link.remove();
    };
  }, []);

  useEffect(() => {
    let alive = true;
    setError(null);
    fetchFullBoard(localDay(new Date()))
      .then((b) => {
        // api.ts returns undefined for an offline-queued miss.
        if (!alive) return;
        if (b) setBoard(b);
        else setError('The board did not load - check the connection.');
      })
      .catch((e) => {
        if (alive) setError(getErrorMessage(e));
      });
    return () => {
      alive = false;
    };
  }, [retryKey]);

  const ready = board !== null;
  useEffect(() => {
    if (!ready || !rootRef.current || engineRef.current || !board) return;
    engineRef.current = bootStandupEngine({
      root: rootRef.current,
      board,
      navigate: (path: string) => navigateRef.current(path),
    });
    const timer = window.setInterval(() => {
      fetchFullBoard(localDay(new Date()))
        .then((b) => {
          if (b && engineRef.current) engineRef.current.refresh(b);
        })
        .catch(() => {
          /* a missed poll is silent; the next one reconciles */
        });
    }, POLL_MS);
    return () => {
      window.clearInterval(timer);
      if (engineRef.current) {
        engineRef.current.dispose();
        engineRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- boot exactly once, on first board
  }, [ready]);

  if (error) {
    return (
      <div className="p-6">
        <p className="mb-3 text-sm text-red-600 dark:text-red-400">{error}</p>
        <button
          type="button"
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600"
          onClick={() => setRetryKey((k) => k + 1)}
        >
          Try again
        </button>
      </div>
    );
  }
  if (!board) {
    return <div className="p-6 text-sm text-gray-500">Loading the board...</div>;
  }

  return (
    <div
      ref={rootRef}
      className="standup-root"
      // Static, trusted template shipped with the bundle - no server or
      // user data reaches it; the engine renders all data through its
      // own esc() helper.
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: STANDUP_MARKUP }}
    />
  );
}
