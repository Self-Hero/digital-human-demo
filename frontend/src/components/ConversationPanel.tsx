import type { SessionState, TranscriptItem } from "../types/conversation";

interface Props {
  state: SessionState;
  transcript: TranscriptItem[];
  error: string | null;
  microphoneActive: boolean;
  onToggleMicrophone: () => Promise<void>;
  onInterrupt: () => void;
}

export function ConversationPanel({
  state,
  transcript,
  error,
  microphoneActive,
  onToggleMicrophone,
  onInterrupt,
}: Props) {
  return (
    <section className="conversation-panel">
      <header>
        <div>
          <p className="eyebrow">REALTIME AUDIO</p>
          <h2>实时语音对话</h2>
        </div>
        <button
          className="interrupt-button"
          type="button"
          onClick={onInterrupt}
          disabled={state !== "thinking" && state !== "speaking"}
        >
          打断回答
        </button>
      </header>

      <div className="transcript" aria-live="polite">
        {transcript.length === 0 ? (
          <div className="empty-transcript">
            点击“开启麦克风”后直接说话。停顿约半秒，数字人就会开始回答。
          </div>
        ) : (
          transcript.map((item) => (
            <article className={`message ${item.role}`} key={item.id}>
              <span>{item.role === "user" ? "你" : "数字人"}</span>
              <p>{item.text}</p>
            </article>
          ))
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="voice-controls">
        <button
          className={`microphone-button ${microphoneActive ? "active" : ""}`}
          type="button"
          onClick={() => void onToggleMicrophone()}
          disabled={state === "connecting"}
        >
          <span className="microphone-indicator" />
          {microphoneActive ? "关闭麦克风" : "开启麦克风"}
        </button>
      </div>
      <p className="hint">
        请使用耳机或开启系统回声消除。API Key 只保存在后端，不会发送到浏览器。
      </p>
    </section>
  );
}
