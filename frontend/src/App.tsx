import { ConversationPanel } from "./components/ConversationPanel";
import { DigitalHumanStage } from "./components/DigitalHumanStage";
import { useConversation } from "./hooks/useConversation";

export default function App() {
  const conversation = useConversation();

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">REALTIME DIGITAL HUMAN</p>
          <h1>实时数字人交互 Demo</h1>
        </div>
        <div className="architecture-pill">LiveTalking · MuseTalk · Cloud AI</div>
      </header>

      <div className="workspace">
        <DigitalHumanStage
          state={conversation.state}
          metrics={conversation.metrics}
        />
        <ConversationPanel
          state={conversation.state}
          transcript={conversation.transcript}
          error={conversation.error}
          onSend={conversation.sendText}
          onInterrupt={conversation.interrupt}
        />
      </div>
    </main>
  );
}
