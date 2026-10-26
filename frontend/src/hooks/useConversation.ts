import { useCallback, useEffect, useRef, useState } from "react";

import {
  createSession,
  deleteSession,
  sessionWebSocketUrl,
} from "../api/client";
import type {
  ServerEvent,
  SessionState,
  TranscriptItem,
  TurnMetrics,
} from "../types/conversation";

function makeId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export function useConversation() {
  const socketRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const assistantItemByTurn = useRef(new Map<string, string>());

  const [state, setState] = useState<SessionState>("connecting");
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [metrics, setMetrics] = useState<TurnMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;

    async function connect() {
      try {
        const sessionId = await createSession();
        if (disposed) {
          await deleteSession(sessionId);
          return;
        }
        sessionIdRef.current = sessionId;
        const socket = new WebSocket(sessionWebSocketUrl(sessionId));
        socketRef.current = socket;

        socket.onmessage = (message) => {
          const event = JSON.parse(message.data) as ServerEvent;

          if (event.type === "session.state" && event.state) {
            setState(event.state);
            return;
          }
          if (event.type === "transcript.user" && event.text) {
            setTranscript((items) => [
              ...items,
              { id: makeId("user"), role: "user", text: event.text! },
            ]);
            return;
          }
          if (event.type === "assistant.delta" && event.turnId && event.delta) {
            const existingId = assistantItemByTurn.current.get(event.turnId);
            if (existingId) {
              setTranscript((items) =>
                items.map((item) =>
                  item.id === existingId
                    ? { ...item, text: item.text + event.delta }
                    : item,
                ),
              );
            } else {
              const id = makeId("assistant");
              assistantItemByTurn.current.set(event.turnId, id);
              setTranscript((items) => [
                ...items,
                { id, role: "assistant", text: event.delta! },
              ]);
            }
            return;
          }
          if (event.type === "turn.completed" && event.metrics) {
            setMetrics(event.metrics);
            return;
          }
          if (event.type === "error") {
            setError(event.message ?? "未知错误");
            setState("error");
          }
        };

        socket.onerror = () => {
          setError("WebSocket连接失败，请确认后端已经启动。");
          setState("error");
        };
        socket.onclose = () => {
          if (!disposed) setState("connecting");
        };
      } catch (connectionError) {
        setError(
          connectionError instanceof Error
            ? connectionError.message
            : "连接后端失败",
        );
        setState("error");
      }
    }

    void connect();
    return () => {
      disposed = true;
      socketRef.current?.close();
      const sessionId = sessionIdRef.current;
      if (sessionId) void deleteSession(sessionId);
    };
  }, []);

  const sendText = useCallback((text: string) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    setError(null);
    setMetrics(null);
    socket.send(JSON.stringify({ type: "user.text", text }));
    return true;
  }, []);

  const interrupt = useCallback(() => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "turn.interrupt" }));
  }, []);

  return { state, transcript, metrics, error, sendText, interrupt };
}
