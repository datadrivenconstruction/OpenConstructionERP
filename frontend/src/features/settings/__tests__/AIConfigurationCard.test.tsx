// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The OpenAI-compatible endpoint card (issue #499).
//
// A self-hosted endpoint behind a gateway needs a bearer key, a model that
// cannot take the tool schema needs tool calling off, and a slow model needs a
// longer timeout. The card used to hide the key field for every self-hosted
// runtime and had no place for the other two, so none of them could be saved.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { AIConfigurationCard } from '../SettingsPage';

const getSettings = vi.fn();
const updateSettings = vi.fn();
const testConnection = vi.fn();

vi.mock('@/features/ai/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/ai/api')>();
  return {
    ...actual,
    aiApi: {
      ...actual.aiApi,
      getSettings: (...args: unknown[]) => getSettings(...args),
      updateSettings: (...args: unknown[]) => updateSettings(...args),
      testConnection: (...args: unknown[]) => testConnection(...args),
    },
  };
});

function settingsFor(provider: string, extra: Record<string, unknown> = {}) {
  return {
    id: 's1',
    user_id: 'u1',
    provider,
    preferred_model: provider,
    model_overrides: {},
    default_models: { vllm: 'meta-llama/Llama-3.1-8B-Instruct', ollama: 'llama3.1' },
    vllm_base_url: 'http://10.20.0.5:4000/v1',
    ollama_base_url: null,
    vllm_api_key_set: false,
    tool_calling: {},
    tool_calling_defaults: { vllm: 'off', ollama: 'off' },
    timeouts: {},
    default_timeout_seconds: 240,
    metadata_: {},
    ...extra,
  };
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <AIConfigurationCard />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('AIConfigurationCard, OpenAI-compatible endpoint', () => {
  beforeEach(() => {
    getSettings.mockReset();
    updateSettings.mockReset().mockResolvedValue({});
    testConnection.mockReset().mockResolvedValue({ success: true, message: 'ok' });
  });

  it('offers an optional key, tool calling and a timeout, and saves all three', async () => {
    getSettings.mockResolvedValue(settingsFor('vllm'));
    renderCard();

    const key = await screen.findByLabelText(/API key \(optional\)/);
    await waitFor(() => expect(screen.getByLabelText('Tool calling')).toBeTruthy());

    fireEvent.change(key, { target: { value: 'sk-gateway' } });
    fireEvent.change(screen.getByLabelText('Tool calling'), { target: { value: 'auto' } });
    fireEvent.change(screen.getByLabelText('Timeout (seconds)'), { target: { value: '900' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    await waitFor(() => expect(updateSettings).toHaveBeenCalled());
    expect(updateSettings).toHaveBeenLastCalledWith({
      preferred_model: 'vllm',
      vllm_api_key: 'sk-gateway',
      tool_calling: { vllm: 'auto' },
      timeouts: { vllm: 900 },
    });
  });

  it('refuses a timeout outside the range and names the range', async () => {
    getSettings.mockResolvedValue(settingsFor('vllm'));
    renderCard();

    // The timeout field shows for every provider, so wait until the saved
    // settings have picked the endpoint before typing into it.
    await screen.findByLabelText('Tool calling');
    fireEvent.change(screen.getByLabelText('Timeout (seconds)'), { target: { value: '5' } });

    // i18next may group the upper bound ("1,800"), so match the digits loosely.
    expect(await screen.findByText(/between 10 and 1\D?800/)).toBeTruthy();
    expect(screen.getByLabelText('Timeout (seconds)').getAttribute('aria-invalid')).toBe('true');
    expect(screen.getByRole('button', { name: 'Save Settings' }).hasAttribute('disabled')).toBe(true);
  });

  it('clears a stored key when the optional field is emptied and saved', async () => {
    getSettings.mockResolvedValue(settingsFor('vllm', { vllm_api_key_set: true }));
    renderCard();

    const key = await screen.findByLabelText(/API key \(optional\)/);
    fireEvent.change(key, { target: { value: 'x' } });
    fireEvent.change(key, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    await waitFor(() => expect(updateSettings).toHaveBeenCalled());
    expect(updateSettings.mock.lastCall[0]).toMatchObject({ preferred_model: 'vllm', vllm_api_key: '' });
  });

  it('keeps Ollama keyless', async () => {
    getSettings.mockResolvedValue(settingsFor('ollama'));
    renderCard();

    await screen.findByLabelText('Tool calling');
    expect(screen.queryByLabelText(/API key/)).toBeNull();
  });
});
