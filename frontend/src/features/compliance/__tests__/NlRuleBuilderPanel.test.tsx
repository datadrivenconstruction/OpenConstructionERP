// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api', () => ({
  parseNlToDsl: vi.fn(),
  listNlPatterns: vi.fn(),
  saveDslRule: vi.fn(),
}));

import { parseNlToDsl, listNlPatterns, saveDslRule } from '../api';
import { NlRuleBuilderPanel } from '../NlRuleBuilderPanel';

const PATTERNS = [
  { pattern_id: 'must_have', name_key: 'compliance.nl.pattern.must_have', confidence: 0.9 },
  { pattern_id: 'count_at_least', name_key: 'compliance.nl.pattern.count_at_least', confidence: 0.86 },
];

const SAMPLE_RESULT = {
  dsl_definition: {
    rule_id: 'custom.wall.has_fire_rating',
    name: 'All wall must have fire rating',
    severity: 'warning',
    scope: 'wall',
    expression: { forEach: 'wall', assert: { '!=': ['wall.fire_rating', null] } },
  },
  dsl_yaml: 'rule_id: custom.wall.has_fire_rating\nname: All wall must have fire rating\n',
  confidence: 0.9,
  used_method: 'pattern' as const,
  matched_pattern: 'must_have',
  errors: [],
  suggestions: [],
};

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <NlRuleBuilderPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  (parseNlToDsl as ReturnType<typeof vi.fn>).mockReset();
  (listNlPatterns as ReturnType<typeof vi.fn>).mockReset();
  (saveDslRule as ReturnType<typeof vi.fn>).mockReset();
  (listNlPatterns as ReturnType<typeof vi.fn>).mockResolvedValue(PATTERNS);
});

describe('NlRuleBuilderPanel', () => {
  it('renders the input, language selector, and Generate button', async () => {
    renderPanel();
    expect(screen.getByTestId('nl-rule-builder-panel')).toBeInTheDocument();
    expect(screen.getByTestId('nl-input')).toBeInTheDocument();
    expect(screen.getByTestId('nl-lang-en')).toBeInTheDocument();
    expect(screen.getByTestId('nl-lang-de')).toBeInTheDocument();
    expect(screen.getByTestId('nl-lang-ru')).toBeInTheDocument();
    expect(screen.getByTestId('nl-generate')).toBeInTheDocument();
    expect(screen.getByTestId('nl-save')).toBeInTheDocument();
  });

  it('disables Generate when the textarea is empty', () => {
    renderPanel();
    const btn = screen.getByTestId('nl-generate');
    expect(btn).toBeDisabled();
  });

  it('calls parseNlToDsl with the user text and selected language', async () => {
    (parseNlToDsl as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      SAMPLE_RESULT,
    );
    renderPanel();

    fireEvent.change(screen.getByTestId('nl-input'), {
      target: { value: 'all walls must have fire_rating' },
    });
    fireEvent.click(screen.getByTestId('nl-lang-de'));
    fireEvent.click(screen.getByTestId('nl-generate'));

    await waitFor(() => {
      expect(parseNlToDsl).toHaveBeenCalledWith({
        text: 'all walls must have fire_rating',
        lang: 'de',
        use_ai: false,
      });
    });
  });

  it('renders the YAML preview after a successful generation', async () => {
    (parseNlToDsl as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      SAMPLE_RESULT,
    );
    renderPanel();

    fireEvent.change(screen.getByTestId('nl-input'), {
      target: { value: 'all walls must have fire_rating' },
    });
    fireEvent.click(screen.getByTestId('nl-generate'));

    await waitFor(() => {
      expect(screen.getByTestId('dsl-preview-yaml')).toBeInTheDocument();
    });
    expect(
      screen.getByTestId('dsl-preview-yaml').textContent,
    ).toContain('custom.wall.has_fire_rating');
  });

  it('calls saveDslRule with the generated YAML when Save is clicked', async () => {
    (parseNlToDsl as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      SAMPLE_RESULT,
    );
    (saveDslRule as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'aaaa',
      rule_id: 'custom.wall.has_fire_rating',
      name: 'All wall must have fire rating',
      severity: 'warning',
      standard: 'custom',
      description: null,
      definition_yaml: SAMPLE_RESULT.dsl_yaml,
      is_active: true,
      created_at: '',
      updated_at: '',
    });

    renderPanel();
    fireEvent.change(screen.getByTestId('nl-input'), {
      target: { value: 'all walls must have fire_rating' },
    });
    fireEvent.click(screen.getByTestId('nl-generate'));

    await waitFor(() => {
      expect(screen.getByTestId('dsl-preview-yaml')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('nl-save'));

    await waitFor(() => {
      expect(saveDslRule).toHaveBeenCalledWith(
        SAMPLE_RESULT.dsl_yaml,
        true,
      );
    });
  });

  it('forwards use_ai when the checkbox is toggled', async () => {
    (parseNlToDsl as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      SAMPLE_RESULT,
    );
    renderPanel();

    fireEvent.change(screen.getByTestId('nl-input'), {
      target: { value: 'all walls must have fire_rating' },
    });
    fireEvent.click(screen.getByTestId('nl-use-ai'));
    fireEvent.click(screen.getByTestId('nl-generate'));

    await waitFor(() => {
      expect(parseNlToDsl).toHaveBeenCalledWith(
        expect.objectContaining({ use_ai: true }),
      );
    });
  });
});
