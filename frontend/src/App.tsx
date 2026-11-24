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
    access.clientId,
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
    await conversation.toggleMicrophone();
  }, [conversation.toggleMicrophone]);

  useEffect(() => {
    if (avatar.connectionState === "failed" && access.ownsConversation) {
      void release();
    }
  }, [access.ownsConversation, avatar.connectionState, release]);

  useEffect(() => {
    if (access.ownsConversation && avatar.sessionId) {
      void access.bindAvatarSession(avatar.sessionId);
    }
  }, [access.bindAvatarSession, access.ownsConversation, avatar.sessionId]);

  useEffect(() => {
    if (
      access.presenceReady &&
      !access.ownsConversation &&
      avatar.connectionState !== "disconnected"
    ) {
      disconnect();
    }
  }, [
    access.ownsConversation,
    access.presenceReady,
    avatar.connectionState,
    disconnect,
  ]);

  const controlledAvatar = {
    ...avatar,
    error: access.error ?? avatar.error,
    connect: connectAvatar,
    disconnect: disconnectAvatar,
  };

  return (
    <main className="app-shell">
      <div
        className="consultation"
        data-connected={avatar.connectionState === "connected"}
        data-state={conversation.state}
      >
        <DigitalHumanStage
          state={conversation.state}
          metrics={conversation.metrics}
          avatar={controlledAvatar}
          onlineClients={access.onlineClients}
          conversationBusy={
            access.conversationActive && !access.ownsConversation
          }
          presenceReady={access.presenceReady}
          connectPending={access.requestPending}
          reclaimPending={access.reclaimPending}
          onReclaimConversation={access.reclaimInactive}
        />
        <ConversationPanel transcript={conversation.transcript} />
        {avatar.connectionState === "connected" && (
          <VoiceControls
            state={conversation.state}
            error={conversation.error}
            microphoneActive={conversation.microphoneActive}
            onToggleMicrophone={toggleMicrophone}
            onInterrupt={conversation.interrupt}
            onDisconnect={disconnectAvatar}
          />
        )}
      </div>
    </main>
  );
}
