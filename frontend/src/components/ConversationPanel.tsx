import type { TranscriptItem } from "../types/conversation";

interface Props {
  transcript: TranscriptItem[];
}

export function ConversationPanel({ transcript }: Props) {
  return (
    <section className="conversation-panel" aria-labelledby="conversation-title">
      <header>
        <h2 id="conversation-title">对话记录</h2>
        <span className="message-count">{transcript.length} 条</span>
      </header>

      <div className="transcript" aria-live="polite">
        {transcript.length === 0 ? (
          <div className="empty-transcript">
            暂无对话
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
    </section>
  );
}
