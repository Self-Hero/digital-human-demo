import { useCallback, useEffect, useRef, useState } from "react";

import {
  acquireConversation,
  presenceWebSocketUrl,
  releaseConversation,
  type ConversationAccessStatus,
} from "../api/client";

const initialStatus: ConversationAccessStatus = {
  onlineClients: 0,
  conversationActive: false,
  ownsConversation: false,
};

export function useConversationAccess() {
  const clientIdRef = useRef(crypto.randomUUID());
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const statusRef = useRef(initialStatus);
  const [status, setStatus] = useState(initialStatus);
  const [presenceReady, setPresenceReady] = useState(false);
  const [requestPending, setRequestPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyStatus = useCallback((next: ConversationAccessStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);

  useEffect(() => {
    let disposed = false;
    let reconnectAttempt = 0;
    let heartbeatTimer: number | null = null;

    const connect = () => {
      if (disposed) return;
      const socket = new WebSocket(
        presenceWebSocketUrl(clientIdRef.current),
      );
      socketRef.current = socket;

      socket.onopen = () => {
        heartbeatTimer = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send("ping");
        }, 10_000);
      };

      socket.onmessage = (event) => {
        const next = JSON.parse(event.data) as ConversationAccessStatus;
        reconnectAttempt = 0;
        setPresenceReady(true);
        setError(null);
        applyStatus(next);
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (heartbeatTimer !== null) {
          window.clearInterval(heartbeatTimer);
          heartbeatTimer = null;
        }
        if (socketRef.current === socket) socketRef.current = null;
        if (disposed) return;
        setPresenceReady(false);
        const delay = Math.min(1_000 * 2 ** reconnectAttempt, 10_000);
        reconnectAttempt += 1;
        reconnectTimerRef.current = window.setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      disposed = true;
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      if (heartbeatTimer !== null) window.clearInterval(heartbeatTimer);
      void releaseConversation(clientIdRef.current, true).catch(
        () => undefined,
      );
      socketRef.current?.close();
    };
  }, [applyStatus]);

  const acquire = useCallback(async (): Promise<boolean> => {
    if (!presenceReady || requestPending) return false;
    setRequestPending(true);
    setError(null);
    try {
      applyStatus(await acquireConversation(clientIdRef.current));
      return true;
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "当前无法开始对话，请稍后再试",
      );
      return false;
    } finally {
      setRequestPending(false);
    }
  }, [applyStatus, presenceReady, requestPending]);

  const release = useCallback(async () => {
    try {
      applyStatus(await releaseConversation(clientIdRef.current));
    } catch {
      // Presence disconnect remains the final cleanup path.
    }
  }, [applyStatus]);

  return {
    ...status,
    presenceReady,
    requestPending,
    error,
    acquire,
    release,
  };
}
