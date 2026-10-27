export type SessionState =
  | "connecting"
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

export interface TranscriptItem {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
}

export interface TurnMetrics {
  firstAudioMs: number | null;
  totalMs: number;
}

export interface ServerEvent {
  type: string;
  sessionId?: string;
  turnId?: string;
  state?: SessionState;
  text?: string;
  delta?: string;
  audio?: string;
  sampleRate?: number;
  inputSampleRate?: number;
  outputSampleRate?: number;
  message?: string;
  metrics?: TurnMetrics;
}
