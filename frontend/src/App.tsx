import { useCallback, useEffect } from "react";

import { ConversationPanel } from "./components/ConversationPanel";
import { DigitalHumanStage } from "./components/DigitalHumanStage";
import { VoiceControls } from "./components/VoiceControls";
import { useAvatarSession } from "./hooks/useAvatarSession";
import { useConversationAccess } from "./hooks/useConversationAccess";
import { useConversation } from "./hooks/useConversation";

export default function App() {
  const avatar = useAvatarSession();
  const access = useConversationAccess();
  const conversation = useConversation(
    avatar.sessionId,
    avatar.connectionState === "connected",
  );
  const { acquire, release } = access;
  const { connect, disconnect } = avatar;

  const connectAvatar = useCallback(async () => {
    if (!(await acquire())) return;
    if (!(await connect())) await release();
  }, [acquire, connect, release]);

  const disconnectAvatar = useCallback(() => {
    disconnect();
    void release();
  }, [disconnect, release]);

  const toggleMicrophone = useCallback(async () => {
    const wasActive = conversation.microphoneActive;
    const isActive = await conversation.toggleMicrophone();
    if (wasActive || !isActive) disconnectAvatar();
  }, [
    conversation.microphoneActive,
    conversation.toggleMicrophone,
    disconnectAvatar,
  ]);

  useEffect(() => {
    if (avatar.connectionState === "failed" && access.ownsConversation) {
      void release();
    }
  }, [access.ownsConversation, avatar.connectionState, release]);

  const controlledAvatar = {
    ...avatar,
    error: access.error ?? avatar.error,
    connect: connectAvatar,
    disconnect: disconnectAvatar,
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">AI</span>
          <div>
            <h1>实时数字人</h1>
            <p>智能交互服务</p>
          </div>
        </div>
        <div className="service-summary" aria-live="polite">
          <span className={`service-state ${access.presenceReady ? "online" : ""}`}>
            <span className="service-dot" />
            {access.presenceReady ? "服务在线" : "正在连接"}
          </span>
          <span className="summary-divider" />
          <span>在线 {access.onlineClients}</span>
          <span>活跃会话 {access.conversationActive ? 1 : 0}</span>
        </div>
      </header>

      <div className="workspace">
        <DigitalHumanStage
          state={conversation.state}
          metrics={conversation.metrics}
          avatar={controlledAvatar}
          conversationBusy={
            access.conversationActive && !access.ownsConversation
          }
          presenceReady={access.presenceReady}
          connectPending={access.requestPending}
        />
        <VoiceControls
          state={conversation.state}
          error={conversation.error}
          microphoneActive={conversation.microphoneActive}
          onToggleMicrophone={toggleMicrophone}
          onInterrupt={conversation.interrupt}
        />
      </div>

      <ConversationPanel transcript={conversation.transcript} />
    </main>
  );
}
