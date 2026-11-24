import { useEffect, useRef } from "react";

import type { TranscriptItem } from "../types/conversation";

interface Props {
  transcript: TranscriptItem[];
}

export function ConversationPanel({ transcript }: Props) {
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = transcriptRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [transcript]);

  if (transcript.length === 0) return null;

  return (
    <section className="conversation-panel" aria-label="实时对话">
      <div className="transcript" ref={transcriptRef} role="log" aria-live="polite">
        {transcript.map((item) => (
          <article className={`message ${item.role}`} key={item.id}>
            <span>{item.role === "user" ? "你" : "数字人"}</span>
            <p>{item.text}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
