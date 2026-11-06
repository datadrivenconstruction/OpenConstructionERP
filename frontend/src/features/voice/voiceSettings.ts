// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The person's voice input preferences, kept in this browser.

import { create } from 'zustand';

const STORAGE_KEY = 'oe_voice_input_v1';

interface Persisted {
  sendOnStop: boolean;
  allowServer: boolean;
}

interface VoiceSettingsState extends Persisted {
  setSendOnStop: (value: boolean) => void;
  setAllowServer: (value: boolean) => void;
}

// Off by default: the text lands in the composer for review, and audio leaves
// the browser only after the person agreed to it.
const DEFAULTS: Persisted = { sendOnStop: false, allowServer: false };

function read(): Persisted {
  if (typeof window === 'undefined') return DEFAULTS;
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<Persisted>;
    return {
      sendOnStop: typeof parsed.sendOnStop === 'boolean' ? parsed.sendOnStop : DEFAULTS.sendOnStop,
      allowServer: typeof parsed.allowServer === 'boolean' ? parsed.allowServer : DEFAULTS.allowServer,
    };
  } catch {
    return DEFAULTS;
  }
}

function write(state: Persisted): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Private mode or a full quota: the setting lasts for this page only.
  }
}

export const useVoiceSettings = create<VoiceSettingsState>((set, get) => ({
  ...read(),
  setSendOnStop: (value) => {
    set({ sendOnStop: value });
    write({ sendOnStop: value, allowServer: get().allowServer });
  },
  setAllowServer: (value) => {
    set({ allowServer: value });
    write({ sendOnStop: get().sendOnStop, allowServer: value });
  },
}));
