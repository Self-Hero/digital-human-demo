import { Mic, MicOff, PhoneOff, Square } from "lucide-react";

import type { SessionState } from "../types/conversation";

interface Props {
  state: SessionState;
  error: string | null;
  microphoneActive: boolean;
  onToggleMicrophone: () => Promise<void>;
  onInterrupt: () => void;
  onDisconnect: () => void;
}

const stateLabels: Record<SessionState, string> = {
  connecting: "正在连接",
  idle: "准备就绪",
  listening: "正在聆听",
  thinking: "正在思考",
  speaking: "正在回答",
  error: "连接异常",
};

export function VoiceControls({
  state,
  error,
  microphoneActive,
  onToggleMicrophone,
  onInterrupt,
  onDisconnect,
}: Props) {
  return (
    <section className="interaction-controls" aria-label="语音控制">
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      <div className="live-state" role="status">
        <span className="live-wave" aria-hidden="true">
          <i /><i /><i /><i /><i />
        </span>
        <span>{stateLabels[state]}</span>
      </div>
      <div className="voice-actions">
        <button
          className={`call-control microphone-button ${microphoneActive ? "active" : ""}`}
          type="button"
          aria-pressed={microphoneActive}
          onClick={() => void onToggleMicrophone()}
          disabled={state === "connecting" || state === "error"}
        >
          <span className="control-icon" aria-hidden="true">
            {microphoneActive ? <Mic size={21} /> : <MicOff size={21} />}
          </span>
          <span>{microphoneActive ? "麦克风" : "已关闭"}</span>
        </button>
        <button
          className="interrupt-button"
          type="button"
          onClick={onInterrupt}
          disabled={state !== "thinking" && state !== "speaking"}
        >
          <Square size={15} aria-hidden="true" />
          <span>打断回答</span>
        </button>
        <button
          className="call-control hangup-button"
          type="button"
          onClick={onDisconnect}
        >
          <span className="control-icon" aria-hidden="true">
            <PhoneOff size={21} />
          </span>
          <span>结束</span>
        </button>
      </div>
    </section>
  );
}
