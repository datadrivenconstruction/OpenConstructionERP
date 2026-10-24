// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Hand-off from the palette (or a header button) to the AI assistant dock.
 *
 * The text is prefilled, never sent: the person reviews it and presses Enter.
 * The dock sends the current page and project with every message itself, and
 * the ids of the actions this browser can run (`assistantActionIds`), so the
 * assistant can propose one of them for the person to confirm.
 */
import { isFloatingChatHiddenOn, useFloatingChatStore } from '@/features/erp-chat/useFloatingChat';
import { listActions } from './registry';

/** Most ids sent with a message; matches MAX_CLIENT_ACTIONS on the server. */
export const MAX_ASSISTANT_ACTIONS = 120;

export interface AskAiOptions {
  /** Current path; on a page that hides the dock the person is taken home first. */
  pathname?: string;
  navigate?: (to: string) => void;
}

function leaveHiddenRoute(opts: AskAiOptions): void {
  if (opts.pathname && opts.navigate && isFloatingChatHiddenOn(opts.pathname)) opts.navigate('/');
}

/** Open the dock as it is. */
export function openAiPanel(opts: AskAiOptions = {}): void {
  leaveHiddenRoute(opts);
  useFloatingChatStore.getState().open();
}

/** Open the dock with `text` waiting in the composer. */
export function askAi(text: string, opts: AskAiOptions = {}): void {
  const prompt = text.trim();
  leaveHiddenRoute(opts);
  if (!prompt) {
    useFloatingChatStore.getState().open();
    return;
  }
  useFloatingChatStore.getState().seedPrompt(prompt);
}

/** Ids the assistant may propose, project-free ones first, capped. */
export function assistantActionIds(enabled: (moduleKey: string) => boolean = () => true): string[] {
  return listActions()
    .filter((a) => !a.moduleKey || enabled(a.moduleKey))
    .sort((a, b) => Number(a.group === 'navigate') - Number(b.group === 'navigate'))
    .map((a) => a.id)
    .slice(0, MAX_ASSISTANT_ACTIONS);
}
