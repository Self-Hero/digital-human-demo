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

export function useAvatarSession() {
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const idleTimerRef = useRef<number | null>(null);
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

  const disconnect = useCallback(() => {
    stopPlaybackEvents();
    const peer = peerRef.current;
    peerRef.current = null;
    peer?.close();
    videoStream?.getTracks().forEach((track) => track.stop());
    audioStream?.getTracks().forEach((track) => track.stop());
    setVideoStream(null);
    setAudioStream(null);
    setSessionId(null);
    setConnectionState("disconnected");
  }, [audioStream, stopPlaybackEvents, videoStream]);

  const connect = useCallback(async () => {
    if (peerRef.current) return;

    setConnectionState("connecting");
    setError(null);
    const turnUrl = import.meta.env.VITE_TURN_URL;
    const peer = new RTCPeerConnection({
      sdpSemantics: "unified-plan",
      iceServers: turnUrl
        ? [
            {
              urls: turnUrl,
              username: import.meta.env.VITE_TURN_USERNAME,
              credential: import.meta.env.VITE_TURN_PASSWORD,
            },
          ]
        : [],
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
      if (peer.connectionState === "connected") setConnectionState("connected");
      if (["failed", "disconnected"].includes(peer.connectionState)) {
        setConnectionState("failed");
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
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const answer = (await response.json()) as {
        sdp?: string;
        type?: RTCSdpType;
        sessionid?: string | number;
        msg?: string;
      };
      if (!answer.sdp || !answer.type) {
        throw new Error(answer.msg ?? "LiveTalking 未返回 SDP");
      }

      await peer.setRemoteDescription({ type: answer.type, sdp: answer.sdp });
      const nextSessionId =
        answer.sessionid == null ? null : String(answer.sessionid);
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
      peer.close();
      peerRef.current = null;
      setConnectionState("failed");
      setError(cause instanceof Error ? cause.message : "数字人连接失败");
    }
  }, [stopPlaybackEvents]);

  useEffect(
    () => () => {
      stopPlaybackEvents();
      peerRef.current?.close();
    },
    [stopPlaybackEvents],
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
