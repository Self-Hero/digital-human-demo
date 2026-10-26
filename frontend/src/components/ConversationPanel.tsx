import { FormEvent, useState } from "react";

import type { SessionState, TranscriptItem } from "../types/conversation";

interface Props {
  state: SessionState;
  transcript: TranscriptItem[];
  error: string | null;
  onSend: (text: string) => boolean;
  onInterrupt: () => void;
}

export function ConversationPanel({
  state,
  transcript,
  error,
  onSend,
  onInterrupt,
}: Props) {
  const [text, setText] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    if (onSend(value)) setText("");
  }

  return (
    <section className="conversation-panel">
      <header>
        <div>
          <p className="eyebrow">DEMO CONTROL</p>
          <h2>对话调试台</h2>
        </div>
        <button
          className="interrupt-button"
          type="button"
          onClick={onInterrupt}
          disabled={state !== "thinking" && state !== "speaking"}
        >
          打断
        </button>
      </header>

      <div className="transcript" aria-live="polite">
        {transcript.length === 0 ? (
          <div className="empty-transcript">
            输入一段文字，验证模拟的流式LLM、TTS和数字人编排链路。
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

      <form className="composer" onSubmit={submit}>
        <input
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="先用文字模拟用户语音，例如：介绍一下这个Demo"
          disabled={state === "connecting" || state === "error"}
        />
        <button type="submit" disabled={!text.trim() || state === "connecting"}>
          发送
        </button>
      </form>
      <p className="hint">麦克风、真实云API和MuseTalk将在后续阶段逐步接入。</p>
    </section>
  );
}
