import { useCallback, useEffect, useRef, useState } from "react";

export type AvatarConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "failed";

function avatarPlaybackStatus(data: string): "start" | "end" | null {
  try {
    const payload = JSON.parse(data) as { status?: unknown };
    if (payload.status === "start" || payload.status === "end") {
      return payload.status;
    }
  } catch {
    // Some LiveTalking versions send Python-style dictionaries over SSE.
  }

  const match = data.match(/["']?status["']?\s*:\s*["'](start|end)["']/i);
  return match?.[1]?.toLowerCase() === "start"
    ? "start"
    : match?.[1]?.toLowerCase() === "end"
      ? "end"
      : null;
}

function releaseAvatarSession(sessionId: string | null): void {
  if (!sessionId) return;
  void fetch(`/avatar-api/session/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    keepalive: true,
  }).catch(() => undefined);
}

export function useAvatarSession() {
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const idleTimerRef = useRef<number | null>(null);
  const disconnectTimerRef = useRef<number | null>(null);
  const [connectionState, setConnectionState] =
    useState<AvatarConnectionState>("disconnected");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [videoStream, setVideoStream] = useState<MediaStream | null>(null);
  const [audioStream, setAudioStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playbackSpeaking, setPlaybackSpeaking] = useState(false);

  const stopPlaybackEvents = useCallback(() => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    if (idleTimerRef.current !== null) {
      window.clearTimeout(idleTimerRef.current);
      idleTimerRef.current = null;
    }
    setPlaybackSpeaking(false);
  }, []);

  const clearDisconnectTimer = useCallback(() => {
    if (disconnectTimerRef.current !== null) {
      window.clearTimeout(disconnectTimerRef.current);
      disconnectTimerRef.current = null;
    }
  }, []);

  const disconnect = useCallback(() => {
    clearDisconnectTimer();
    stopPlaybackEvents();
    const peer = peerRef.current;
    peerRef.current = null;
    peer?.close();
    releaseAvatarSession(sessionIdRef.current);
    sessionIdRef.current = null;
    videoStream?.getTracks().forEach((track) => track.stop());
    audioStream?.getTracks().forEach((track) => track.stop());
    setVideoStream(null);
    setAudioStream(null);
    setSessionId(null);
    setConnectionState("disconnected");
  }, [audioStream, clearDisconnectTimer, stopPlaybackEvents, videoStream]);

  const connect = useCallback(async () => {
    if (peerRef.current) {
      disconnect();
    }

    setConnectionState("connecting");
    setError(null);
    const stunUrl = import.meta.env.VITE_STUN_URL;
    const turnUrl = import.meta.env.VITE_TURN_URL;
    const iceServers: RTCIceServer[] = [];
    if (stunUrl) iceServers.push({ urls: stunUrl });
    if (turnUrl) {
      iceServers.push({
        urls: turnUrl,
        username: import.meta.env.VITE_TURN_USERNAME,
        credential: import.meta.env.VITE_TURN_PASSWORD,
      });
    }
    const peer = new RTCPeerConnection({
      sdpSemantics: "unified-plan",
      iceServers,
      iceTransportPolicy: turnUrl ? "relay" : "all",
    });
    peerRef.current = peer;

    peer.addTransceiver("video", { direction: "recvonly" });
    peer.addTransceiver("audio", { direction: "recvonly" });
    peer.addEventListener("track", (event) => {
      const stream = event.streams[0] ?? new MediaStream([event.track]);
      if (event.track.kind === "video") setVideoStream(stream);
      if (event.track.kind === "audio") setAudioStream(stream);
    });
    peer.addEventListener("connectionstatechange", () => {
      if (peer.connectionState === "connected") {
        clearDisconnectTimer();
        setConnectionState("connected");
      }
      if (peer.connectionState === "disconnected") {
        clearDisconnectTimer();
        disconnectTimerRef.current = window.setTimeout(() => {
          disconnectTimerRef.current = null;
          if (peer.connectionState === "disconnected" && peerRef.current === peer) {
            peerRef.current = null;
            peer.close();
            releaseAvatarSession(sessionIdRef.current);
            sessionIdRef.current = null;
            stopPlaybackEvents();
            setSessionId(null);
            setVideoStream(null);
            setAudioStream(null);
            setConnectionState("failed");
            setError("数字人连接已断开，请重新连接");
          }
        }, 5_000);
      }
      if (
        peer.connectionState === "failed" ||
        (peer.connectionState === "closed" && peerRef.current === peer)
      ) {
        clearDisconnectTimer();
        if (peerRef.current === peer) peerRef.current = null;
        peer.close();
        releaseAvatarSession(sessionIdRef.current);
        sessionIdRef.current = null;
        stopPlaybackEvents();
        setSessionId(null);
        setVideoStream(null);
        setAudioStream(null);
        setConnectionState("failed");
        setError("数字人连接失败，请重新连接");
      }
    });

    try {
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      if (peer.iceGatheringState !== "complete") {
        await new Promise<void>((resolve) => {
          const timeout = window.setTimeout(resolve, 5_000);
          const handleChange = () => {
            if (peer.iceGatheringState === "complete") {
              window.clearTimeout(timeout);
              peer.removeEventListener("icegatheringstatechange", handleChange);
              resolve();
            }
          };
          peer.addEventListener("icegatheringstatechange", handleChange);
        });
      }

      const response = await fetch("/avatar-api/offer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sdp: peer.localDescription?.sdp,
          type: peer.localDescription?.type,
          avatar: import.meta.env.VITE_AVATAR_ID ?? "ma_renda_dynamic",
        }),
      });
      const answer = (await response.json()) as {
        sdp?: string;
        type?: RTCSdpType;
        sessionid?: string | number;
        msg?: string;
      };
      if (!response.ok) {
        throw new Error(answer.msg ?? `HTTP ${response.status}`);
      }
      if (!answer.sdp || !answer.type) {
        throw new Error(answer.msg ?? "LiveTalking 未返回 SDP");
      }

      await peer.setRemoteDescription({ type: answer.type, sdp: answer.sdp });
      const nextSessionId =
        answer.sessionid == null ? null : String(answer.sessionid);
      sessionIdRef.current = nextSessionId;
      setSessionId(nextSessionId);

      stopPlaybackEvents();
      const eventUrl = new URL("/avatar-api/sse", window.location.href);
      if (nextSessionId) eventUrl.searchParams.set("sessionid", nextSessionId);
      const eventSource = new EventSource(eventUrl);
      eventSourceRef.current = eventSource;
      eventSource.onmessage = (event) => {
        const status = avatarPlaybackStatus(event.data);
        if (status === "start") {
          if (idleTimerRef.current !== null) {
            window.clearTimeout(idleTimerRef.current);
            idleTimerRef.current = null;
          }
          setPlaybackSpeaking(true);
        } else if (status === "end") {
          if (idleTimerRef.current !== null) {
            window.clearTimeout(idleTimerRef.current);
          }
          // Let the last generated frames drain before covering the video.
          idleTimerRef.current = window.setTimeout(() => {
            setPlaybackSpeaking(false);
            idleTimerRef.current = null;
          }, 160);
        }
      };
    } catch (cause) {
      clearDisconnectTimer();
      peer.close();
      peerRef.current = null;
      releaseAvatarSession(sessionIdRef.current);
      sessionIdRef.current = null;
      setConnectionState("failed");
      const message = cause instanceof Error ? cause.message : "数字人连接失败";
      setError(
        message.includes("Maximum session limit reached")
          ? "数字人正在被另一个页面使用，请关闭其他页面后重试"
          : message,
      );
    }
  }, [clearDisconnectTimer, disconnect, stopPlaybackEvents]);

  useEffect(
    () => () => {
      stopPlaybackEvents();
      clearDisconnectTimer();
      peerRef.current?.close();
      releaseAvatarSession(sessionIdRef.current);
      sessionIdRef.current = null;
    },
    [clearDisconnectTimer, stopPlaybackEvents],
  );

  return {
    connectionState,
    sessionId,
    videoStream,
    audioStream,
    playbackSpeaking,
    error,
    connect,
    disconnect,
  };
}
