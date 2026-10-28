// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Yield control to the event loop between tile parses so input and rendering
 * stay responsive while a model streams in.
 *
 * Prefers the Scheduler API's `scheduler.yield()` where the browser provides it
 * (current Chromium, our site target): it hands control back to the browser for
 * input and paint and then resumes THIS streaming task at a raised priority. A
 * plain `setTimeout(0)` also yields, but the browser clamps nested timeouts to
 * ~4 ms, and that clamp is dead time between parses that stretches a many-tile
 * stream for no benefit. `scheduler.yield()` keeps the same responsiveness
 * without paying it. Everywhere the API is missing we fall back to `setTimeout`,
 * which is universal and behaves exactly as the loader did before, so there is
 * no regression on older engines.
 */
interface SchedulerYield {
  yield?: () => Promise<void>;
}

export function yieldToEventLoop(): Promise<void> {
  const scheduler = (globalThis as typeof globalThis & { scheduler?: SchedulerYield }).scheduler;
  if (scheduler && typeof scheduler.yield === 'function') {
    // scheduler.yield() rejects if its task is aborted; a streaming pass must
    // never break on the yield itself, so swallow any failure and continue.
    return scheduler.yield().catch(() => undefined);
  }
  return new Promise((resolve) => setTimeout(resolve, 0));
}
