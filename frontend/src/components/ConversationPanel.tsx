import type { TranscriptItem } from "../types/conversation";

interface Props {
  transcript: TranscriptItem[];
}

export function ConversationPanel({ transcript }: Props) {
  return (
    <section className="conversation-panel" aria-labelledby="conversation-title">
      <header>
        <div>
          <p className="eyebrow">CONVERSATION HISTORY</p>
          <h2 id="conversation-title">聊天记录</h2>
        </div>
      </header>

      <div className="transcript" aria-live="polite">
        {transcript.length === 0 ? (
          <div className="empty-transcript">
            暂无聊天记录
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
