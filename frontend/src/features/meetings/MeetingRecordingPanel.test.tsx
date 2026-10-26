// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for minutes from audio. The server, the microphone and the
// speech service are all mocked: what is asserted is the order a meeting
// secretary goes through - nothing can be recorded or uploaded before consent,
// a typed transcript needs no consent, and a proposal is applied only by an
// explicit confirm carrying the reviewer's edits.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./audioApi', () => ({
  fetchSpeechCapabilities: vi.fn(),
  fetchRecordings: vi.fn(),
  fetchMeetingValidation: vi.fn().mockResolvedValue({ status: 'passed', score: 1, errors: 0, warnings: 0, results: [] }),
  createRecording: vi.fn(),
  updateRecording: vi.fn(),
  retranscribeRecording: vi.fn(),
  proposeMinutes: vi.fn(),
  reviewProposals: vi.fn(),
  deleteRecordingAudio: vi.fn(),
  deleteRecording: vi.fn(),
  getRecordingAudioUrl: (id: string) => `/api/v1/meetings/recordings/${id}/audio`,
  fetchGlossary: vi.fn().mockResolvedValue([]),
  addGlossaryTerm: vi.fn(),
  updateGlossaryTerm: vi.fn(),
  deleteGlossaryTerm: vi.fn(),
  seedGlossary: vi.fn(),
}));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: vi.fn() }),
}));

import * as api from './audioApi';
import type { MeetingRecording, SpeechCapabilities } from './audioApi';
import { MeetingRecordingPanel } from './MeetingRecordingPanel';

const caps = (over: Partial<SpeechCapabilities> = {}): SpeechCapabilities => ({
  server_transcription: true,
  provider: 'hosted',
  llm_available: true,
  max_upload_mb: 25,
  accepted_formats: ['m4a', 'mp3', 'webm'],
  default_retention_days: 30,
  max_retention_days: 365,
  ...over,
});

const recording = (over: Partial<MeetingRecording> = {}): MeetingRecording => ({
  id: 'rec-1',
  project_id: 'p-1',
  meeting_id: 'm-1',
  source: 'manual',
  status: 'transcribed',
  has_audio: false,
  audio_filename: null,
  audio_size_bytes: null,
  duration_seconds: null,
  audio_expires_at: null,
  audio_deleted_at: null,
  delete_audio_after_transcription: false,
  consent_confirmed_at: null,
  language: 'en',
  transcript: 'Anna: Send the rebar drawings by Friday.',
  segments: [{ start: null, end: null, speaker: 'Anna', text: 'Send the rebar drawings by Friday.' }],
  speakers: {},
  provider: null,
  transcription_error: null,
  proposals: {},
  glossary_replacements: 0,
  created_at: '2026-10-25T10:00:00Z',
  ...over,
});

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MeetingRecordingPanel
        meetingId="m-1"
        projectId="p-1"
        attendees={[{ name: 'Anna Berg', user_id: '11111111-1111-1111-1111-111111111111' }]}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchSpeechCapabilities).mockResolvedValue(caps());
  vi.mocked(api.fetchRecordings).mockResolvedValue([]);
});

describe('MeetingRecordingPanel', () => {
  it('keeps upload disabled until consent is confirmed', async () => {
    renderPanel();
    fireEvent.click(await screen.findByTestId('add-recording'));
    const upload = await screen.findByTestId('upload-audio');
    expect(upload).toBeDisabled();
    fireEvent.click(screen.getByTestId('consent-checkbox'));
    expect(upload).not.toBeDisabled();
  });

  it('hides audio upload and retention when the server has no speech service', async () => {
    vi.mocked(api.fetchSpeechCapabilities).mockResolvedValue(caps({ server_transcription: false, provider: null }));
    renderPanel();
    expect(await screen.findByTestId('speech-capability-note')).toHaveTextContent(/No speech service/);
    fireEvent.click(screen.getByTestId('add-recording'));
    await screen.findByTestId('recording-consent');
    expect(screen.queryByTestId('upload-audio')).toBeNull();
    expect(screen.queryByTestId('delete-after-checkbox')).toBeNull();
  });

  it('saves a typed transcript as a manual recording', async () => {
    vi.mocked(api.createRecording).mockResolvedValue(recording());
    renderPanel();
    fireEvent.click(await screen.findByTestId('add-recording'));
    fireEvent.click(await screen.findByTestId('type-transcript'));
    fireEvent.change(screen.getByTestId('typed-transcript'), {
      target: { value: 'Anna: Send the rebar drawings by Friday.' },
    });
    fireEvent.click(screen.getByTestId('save-typed'));
    await waitFor(() => expect(api.createRecording).toHaveBeenCalledTimes(1));
    const [meetingId, input] = vi.mocked(api.createRecording).mock.calls[0]!;
    expect(meetingId).toBe('m-1');
    expect(input).toMatchObject({ source: 'manual', consentConfirmed: false });
    expect(input.segments?.[0]).toMatchObject({ speaker: 'Anna' });
  });

  it('applies an action only through confirm, with the edited due date', async () => {
    const withProposals = recording({
      proposals: {
        ai_generated: true,
        items: [
          {
            id: 'a1',
            kind: 'action',
            status: 'pending',
            text: 'Send the rebar drawings',
            confidence: 0.82,
            owner_name: 'Anna Berg',
            owner_contact_id: '11111111-1111-1111-1111-111111111111',
            due_date: null,
            due_hint: 'Friday',
          },
        ],
      },
    });
    vi.mocked(api.fetchRecordings).mockResolvedValue([withProposals]);
    vi.mocked(api.reviewProposals).mockResolvedValue({
      recording: { ...withProposals, proposals: { items: [] } },
      confirmed: 1,
      rejected: 0,
      actions_created: ['act-1'],
      tasks_created: ['task-1'],
      errors: [],
    });
    renderPanel();
    const confirmBtn = await screen.findByTestId('proposal-confirm-a1');
    expect(confirmBtn).toBeDisabled();
    expect(screen.getByTestId('proposal-problems-a1')).toHaveTextContent('Set a due date.');
    fireEvent.change(screen.getByTestId('proposal-due-a1'), { target: { value: '2026-10-30' } });
    expect(confirmBtn).not.toBeDisabled();
    fireEvent.click(confirmBtn);
    await waitFor(() => expect(api.reviewProposals).toHaveBeenCalledTimes(1));
    const [recId, items, createTasks] = vi.mocked(api.reviewProposals).mock.calls[0]!;
    expect(recId).toBe('rec-1');
    expect(createTasks).toBe(true);
    expect(items).toEqual([
      expect.objectContaining({ id: 'a1', decision: 'confirm', due_date: '2026-10-30', owner_name: 'Anna Berg' }),
    ]);
  });

  it('shows failing recording checks as translated badges', async () => {
    vi.mocked(api.fetchRecordings).mockResolvedValue([recording()]);
    vi.mocked(api.fetchMeetingValidation).mockResolvedValue({
      status: 'warnings',
      score: 0.5,
      errors: 0,
      warnings: 1,
      results: [
        { rule_id: 'meetings.proposals_reviewed', severity: 'warning', passed: false, message: 'x', element_ref: 'rec-1' },
        { rule_id: 'meetings.minutes_ready', severity: 'error', passed: false, message: 'y', element_ref: null },
      ],
    });
    renderPanel();
    const checks = await screen.findByTestId('meeting-checks');
    expect(checks).toHaveTextContent('Proposals are waiting for review');
    expect(checks.children).toHaveLength(1);
  });

  it('rejects without sending edits', async () => {
    vi.mocked(api.fetchRecordings).mockResolvedValue([
      recording({
        proposals: {
          items: [{ id: 'd1', kind: 'decision', status: 'pending', text: 'Pour moves to Friday', confidence: 0.35 }],
        },
      }),
    ]);
    vi.mocked(api.reviewProposals).mockResolvedValue({
      recording: recording(),
      confirmed: 0,
      rejected: 1,
      actions_created: [],
      tasks_created: [],
      errors: [],
    });
    renderPanel();
    fireEvent.click(await screen.findByTestId('proposal-reject-d1'));
    await waitFor(() =>
      expect(api.reviewProposals).toHaveBeenCalledWith('rec-1', [{ id: 'd1', decision: 'reject' }], true),
    );
  });
});
