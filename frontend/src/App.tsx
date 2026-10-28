import { ConversationPanel } from "./components/ConversationPanel";
import { DigitalHumanStage } from "./components/DigitalHumanStage";
import { VoiceControls } from "./components/VoiceControls";
import { useAvatarSession } from "./hooks/useAvatarSession";
import { useConversation } from "./hooks/useConversation";

export default function App() {
  const avatar = useAvatarSession();
  const conversation = useConversation(
    avatar.sessionId,
    avatar.connectionState === "connected",
  );

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">REALTIME DIGITAL HUMAN</p>
          <h1>实时数字人交互 Demo</h1>
        </div>
        <div className="architecture-pill">Bailian Realtime · MuseTalk</div>
      </header>

      <div className="workspace">
        <DigitalHumanStage
          state={conversation.state}
          metrics={conversation.metrics}
          avatar={avatar}
        />
        <VoiceControls
          state={conversation.state}
          error={conversation.error}
          microphoneActive={conversation.microphoneActive}
          onToggleMicrophone={conversation.toggleMicrophone}
          onInterrupt={conversation.interrupt}
        />
      </div>

      <ConversationPanel transcript={conversation.transcript} />
    </main>
  );
}
