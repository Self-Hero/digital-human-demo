import type { SessionState } from "../types/conversation";

interface Props {
  state: SessionState;
  error: string | null;
  microphoneActive: boolean;
  onToggleMicrophone: () => Promise<void>;
  onInterrupt: () => void;
}

export function VoiceControls({
  state,
  error,
  microphoneActive,
  onToggleMicrophone,
  onInterrupt,
}: Props) {
  return (
    <section className="interaction-controls" aria-label="语音控制">
      <div className="voice-actions">
        <button
          className={`microphone-button ${microphoneActive ? "active" : ""}`}
          type="button"
          aria-pressed={microphoneActive}
          onClick={() => void onToggleMicrophone()}
          disabled={state === "connecting"}
        >
          <span className="microphone-indicator" aria-hidden="true" />
          {microphoneActive ? "关闭麦克风" : "开启麦克风"}
        </button>
        <button
          className="interrupt-button"
          type="button"
          onClick={onInterrupt}
          disabled={state !== "thinking" && state !== "speaking"}
        >
          打断回答
        </button>
      </div>
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
    </section>
  );
}
