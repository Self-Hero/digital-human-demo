import { useCallback, useEffect, useRef, useState } from "react";

import {
  createSession,
  deleteSession,
  realtimeWebSocketUrl,
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

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary);
}

function downsampleToPcm16(input: Float32Array, inputRate: number): Uint8Array {
  const ratio = inputRate / 16_000;
  const outputLength = Math.max(1, Math.floor(input.length / ratio));
  const buffer = new ArrayBuffer(outputLength * 2);
  const view = new DataView(buffer);

  for (let outputIndex = 0; outputIndex < outputLength; outputIndex += 1) {
    const start = Math.floor(outputIndex * ratio);
    const end = Math.min(input.length, Math.floor((outputIndex + 1) * ratio));
    let sum = 0;
    for (let inputIndex = start; inputIndex < end; inputIndex += 1) {
      sum += input[inputIndex];
    }
    const sample = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
    view.setInt16(
      outputIndex * 2,
      sample < 0 ? sample * 0x8000 : sample * 0x7fff,
      true,
    );
  }
  return new Uint8Array(buffer);
}

export function useConversation(avatarSessionId: string | null) {
  const socketRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const assistantItemByTurn = useRef(new Map<string, string>());
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const microphoneSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const silentGainRef = useRef<GainNode | null>(null);
  const playbackSourcesRef = useRef(new Set<AudioBufferSourceNode>());
  const nextPlaybackAtRef = useRef(0);
  const avatarSessionIdRef = useRef(avatarSessionId);

  const [state, setState] = useState<SessionState>("connecting");
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [metrics, setMetrics] = useState<TurnMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [microphoneActive, setMicrophoneActive] = useState(false);

  const clearPlayback = useCallback(() => {
    for (const source of playbackSourcesRef.current) {
      try {
        source.stop();
      } catch {
        // The source may already have finished.
      }
    }
    playbackSourcesRef.current.clear();
    const context = audioContextRef.current;
    nextPlaybackAtRef.current = context?.currentTime ?? 0;
  }, []);

  const playPcm16 = useCallback((base64Audio: string, sampleRate: number) => {
    const context = audioContextRef.current;
    if (!context || context.state === "closed") return;

    const binary = atob(base64Audio);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    const view = new DataView(bytes.buffer);
    const sampleCount = Math.floor(bytes.byteLength / 2);
    const audioBuffer = context.createBuffer(1, sampleCount, sampleRate);
    const channel = audioBuffer.getChannelData(0);
    for (let index = 0; index < sampleCount; index += 1) {
      channel[index] = view.getInt16(index * 2, true) / 0x8000;
    }

    const source = context.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(context.destination);
    playbackSourcesRef.current.add(source);
    source.onended = () => playbackSourcesRef.current.delete(source);

    const startAt = Math.max(context.currentTime + 0.04, nextPlaybackAtRef.current);
    source.start(startAt);
    nextPlaybackAtRef.current = startAt + audioBuffer.duration;
  }, []);

  const releaseMicrophone = useCallback(() => {
    processorRef.current?.disconnect();
    microphoneSourceRef.current?.disconnect();
    silentGainRef.current?.disconnect();
    processorRef.current = null;
    microphoneSourceRef.current = null;
    silentGainRef.current = null;
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    setMicrophoneActive(false);
  }, []);

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
        const socket = new WebSocket(realtimeWebSocketUrl(sessionId));
        socketRef.current = socket;

        socket.onmessage = (message) => {
          const event = JSON.parse(message.data) as ServerEvent;

          if (event.type === "realtime.ready") {
            const activeAvatarSession = avatarSessionIdRef.current;
            if (activeAvatarSession) {
              socket.send(
                JSON.stringify({
                  type: "avatar.session.attach",
                  sessionId: activeAvatarSession,
                }),
              );
            }
            setError(null);
            setState("idle");
            return;
          }
          if (event.type === "session.state" && event.state) {
            setState(event.state);
            return;
          }
          if (event.type === "playback.clear") {
            clearPlayback();
            return;
          }
          if (event.type === "audio.delta" && event.audio) {
            if (!avatarSessionIdRef.current) {
              playPcm16(event.audio, event.sampleRate ?? 24_000);
            }
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
          if (event.type === "assistant.done" && event.turnId && event.text) {
            const existingId = assistantItemByTurn.current.get(event.turnId);
            if (existingId) {
              setTranscript((items) =>
                items.map((item) =>
                  item.id === existingId ? { ...item, text: event.text! } : item,
                ),
              );
            }
            return;
          }
          if (event.type === "turn.completed" && event.metrics) {
            setMetrics(event.metrics);
            return;
          }
          if (event.type === "error") {
            setError(event.message ?? "实时语音发生未知错误");
            setState("error");
          }
        };

        socket.onerror = () => {
          setError("实时语音 WebSocket 连接失败，请确认后端已经启动。");
          setState("error");
        };
        socket.onclose = () => {
          if (!disposed) {
            releaseMicrophone();
            setState("connecting");
          }
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
      releaseMicrophone();
      clearPlayback();
      socketRef.current?.close();
      void audioContextRef.current?.close();
      const sessionId = sessionIdRef.current;
      if (sessionId) void deleteSession(sessionId);
    };
  }, [clearPlayback, playPcm16, releaseMicrophone]);

  useEffect(() => {
    avatarSessionIdRef.current = avatarSessionId;
    const socket = socketRef.current;
    if (avatarSessionId && socket?.readyState === WebSocket.OPEN) {
      socket.send(
        JSON.stringify({
          type: "avatar.session.attach",
          sessionId: avatarSessionId,
        }),
      );
    }
  }, [avatarSessionId]);

  const startMicrophone = useCallback(async () => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setError("实时语音连接尚未就绪");
      return;
    }

    try {
      let context = audioContextRef.current;
      if (!context || context.state === "closed") {
        context = new AudioContext({ latencyHint: "interactive" });
        audioContextRef.current = context;
      }
      await context.resume();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mediaStreamRef.current = stream;
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const silentGain = context.createGain();
      silentGain.gain.value = 0;

      processor.onaudioprocess = (audioEvent) => {
        const activeSocket = socketRef.current;
        if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return;
        const pcm = downsampleToPcm16(
          audioEvent.inputBuffer.getChannelData(0),
          context.sampleRate,
        );
        activeSocket.send(
          JSON.stringify({ type: "input_audio.append", audio: bytesToBase64(pcm) }),
        );
      };

      source.connect(processor);
      processor.connect(silentGain);
      silentGain.connect(context.destination);
      microphoneSourceRef.current = source;
      processorRef.current = processor;
      silentGainRef.current = silentGain;
      setError(null);
      setMicrophoneActive(true);
      setState("listening");
    } catch (microphoneError) {
      releaseMicrophone();
      setError(
        microphoneError instanceof Error
          ? `无法使用麦克风：${microphoneError.message}`
          : "无法使用麦克风",
      );
      setState("error");
    }
  }, [releaseMicrophone]);

  const stopMicrophone = useCallback(() => {
    releaseMicrophone();
    setState("idle");
  }, [releaseMicrophone]);

  const toggleMicrophone = useCallback(async () => {
    if (mediaStreamRef.current) {
      stopMicrophone();
    } else {
      await startMicrophone();
    }
  }, [startMicrophone, stopMicrophone]);

  const interrupt = useCallback(() => {
    clearPlayback();
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "turn.interrupt" }));
  }, [clearPlayback]);

  return {
    state,
    transcript,
    metrics,
    error,
    microphoneActive,
    toggleMicrophone,
    interrupt,
  };
}
