// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The card's own tests cover what the card says. These cover the wiring around
// it, which is a different thing and was covered by nothing: the step decides
// whether to ask the server for the encoder at all, and it decides using a
// value seeded from the deployment.
//
// Only two behaviours are worth pinning here, because only these two regress
// silently. A tick hardcoded to on looks identical on screen to a tick seeded
// from a server that said on, and the difference only shows on a server
// deployment, where it starts a download nobody asked for. And a request fired
// on a model that has already been requested is invisible too, because the
// second request succeeds just as quietly as the first.
//
// Two things are deliberately not mocked. react-i18next stays real: mocking it
// proves a defaultValue is spelled correctly and proves nothing about what a
// reader sees, since a key that exists in en.ts never reaches its fallback. And
// the api modules are spread from the real ones with importOriginal rather than
// replaced, so anything the step reaches beyond the two network calls stubbed
// here keeps working instead of arriving undefined.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// vi.mock is hoisted above every const in this file, so a factory that closes
// over an ordinary top-level binding reads it before initialisation. vi.hoisted
// lifts these with it.
const { embeddingModelStatus, installEmbeddingModel } = vi.hoisted(() => ({
  embeddingModelStatus: vi.fn(),
  installEmbeddingModel: vi.fn(),
}));

vi.mock('@/features/ai-estimator/api', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    aiEstimatorApi: { ...actual.aiEstimatorApi, embeddingModelStatus, installEmbeddingModel },
  };
});

// The catalogue is a network read this step makes for a different card. Stubbed
// to keep the test off the wire, not because it is under test.
vi.mock('@/features/costs/baseCatalog', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useBaseCatalog: () => ({ data: undefined }) };
});

import { StepDataSetup } from '../OnboardingWizard';

function statusOf(overrides = {}) {
  return {
    state: 'not_requested',
    enabled: true,
    model: 'intfloat/multilingual-e5-small',
    installed: false,
    percent: 0,
    files_done: 0,
    files_total: 0,
    downloaded_bytes: 0,
    error: '',
    library_installed: true,
    env_var: 'OE_DOWNLOAD_EMBEDDING_MODEL',
    locked: false,
    message: '',
    ...overrides,
  };
}

function renderStep(props = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onNext = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <StepDataSetup
        onNext={onNext}
        onBack={() => undefined}
        selectedLang="en"
        backgroundLoad={false}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { ...view, onNext };
}

/**
 * The step renders two switches with identical accessible names, the demo
 * toggle and the encoder toggle, so neither can be addressed by role alone and
 * picking one by index would silently follow the DOM order around.
 *
 * Ascending from the card's own heading finds the card's container before any
 * ancestor wide enough to hold the other switch, which is what makes this the
 * encoder's toggle rather than whichever one happens to come first.
 */
async function encoderSwitch() {
  const heading = await screen.findByText(/Semantic search model/i);
  let node = heading;
  while (node && node !== document.body) {
    const found = node.querySelector?.('[role="switch"]');
    if (found) return found;
    node = node.parentElement;
  }
  throw new Error('found the semantic card heading but no switch beneath it');
}

describe('StepDataSetup, the semantic model wiring', () => {
  beforeEach(() => {
    embeddingModelStatus.mockReset();
    installEmbeddingModel.mockReset();
    installEmbeddingModel.mockResolvedValue({});
  });

  it('takes the tick from what the deployment reports, rather than defaulting it on', async () => {
    // A server deployment answers enabled: false. Hardcoding the tick to true
    // would make a click through the wizard start a download on a machine whose
    // operator had already said no.
    embeddingModelStatus.mockResolvedValue(statusOf({ enabled: false }));

    renderStep();

    await waitFor(async () =>
      expect((await encoderSwitch()).getAttribute('aria-checked')).toBe('false'),
    );
  });

  it('does not ask again for a model this deployment has already requested', async () => {
    embeddingModelStatus.mockResolvedValue(statusOf({ state: 'ready', installed: true }));

    const { onNext } = renderStep();
    // Wait for the status to land: asserting on a request that was never made
    // would pass just as well before the answer arrives.
    await waitFor(async () =>
      expect((await encoderSwitch()).getAttribute('aria-checked')).toBe('true'),
    );

    fireEvent.click(screen.getByRole('button', { name: /Continue/i }));

    // onNext proves the handler actually ran. Without it this test passes on a
    // button that was never wired to anything.
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(installEmbeddingModel).not.toHaveBeenCalled();
  });

  it('does ask when nothing has requested the model yet', async () => {
    // The control for the test above: it establishes that the guard is what
    // withholds the request, not that the request is never sent at all.
    embeddingModelStatus.mockResolvedValue(statusOf({ state: 'not_requested', enabled: true }));

    const { onNext } = renderStep();
    await waitFor(async () =>
      expect((await encoderSwitch()).getAttribute('aria-checked')).toBe('true'),
    );

    fireEvent.click(screen.getByRole('button', { name: /Continue/i }));

    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(installEmbeddingModel).toHaveBeenCalled();
  });

  it('leaves the model unticked when the status cannot be read, so Continue downloads nothing', async () => {
    // The tick is consent to a ~470 MB download. An unknown deployment must not
    // be treated as a yes, which is what the old `?? true` fallback did.
    embeddingModelStatus.mockRejectedValue(new Error('unreachable'));

    const { onNext } = renderStep();
    await waitFor(async () =>
      expect((await encoderSwitch()).getAttribute('aria-checked')).toBe('false'),
    );

    fireEvent.click(screen.getByRole('button', { name: /Continue/i }));

    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(installEmbeddingModel).not.toHaveBeenCalled();
  });
});
