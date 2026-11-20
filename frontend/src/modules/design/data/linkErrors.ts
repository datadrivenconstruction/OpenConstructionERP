// Design module (ERP side of the design editor link).
/** Maps a failed link request to a message key that says what to do next; no React, so it is tested alone. */

export interface LinkFailure {
  key: string;
  /** Whether pressing the same button again can succeed without anyone else acting first. */
  retry: boolean;
}

const statusOf = (err: unknown): number | null => {
  const s = (err as { status?: unknown } | null)?.status;
  return typeof s === 'number' ? s : null;
};

/** The server speaks English to machines; the person gets a sentence with the next step. */
export function linkFailure(err: unknown): LinkFailure {
  const status = statusOf(err);
  if (status === null) {
    const network = err instanceof TypeError || (err instanceof Error && /fetch|network/i.test(err.message));
    return network ? { key: 'design.editor.err_network', retry: true } : { key: 'design.editor.err_other', retry: true };
  }
  if (status === 401) return { key: 'design.editor.err_session', retry: false };
  if (status === 403) return { key: 'design.editor.err_forbidden', retry: false };
  if (status === 404) return { key: 'design.editor.err_not_found', retry: false };
  if (status === 426) return { key: 'design.editor.err_version', retry: false };
  if (status === 429) return { key: 'design.editor.err_throttled', retry: true };
  if (status === 503) return { key: 'design.editor.err_public_url', retry: true };
  if (status >= 500) return { key: 'design.editor.err_server', retry: true };
  return { key: 'design.editor.err_other', retry: true };
}

/** Whole minutes a link stays valid, for "open it within N minutes"; at least one. */
export function minutesLeft(expiresAt: string, now: number = Date.now()): number {
  const at = Date.parse(expiresAt);
  if (Number.isNaN(at)) return 1;
  return Math.max(1, Math.round((at - now) / 60_000));
}
