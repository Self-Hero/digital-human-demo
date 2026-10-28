import { useCallback, useEffect, useRef, useState } from "react";

export type AvatarConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "failed";

export function useAvatarSession() {
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const [connectionState, setConnectionState] =
    useState<AvatarConnectionState>("disconnected");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [videoStream, setVideoStream] = useState<MediaStream | null>(null);
  const [audioStream, setAudioStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);

  const disconnect = useCallback(() => {
    const peer = peerRef.current;
    peerRef.current = null;
    peer?.close();
    videoStream?.getTracks().forEach((track) => track.stop());
    audioStream?.getTracks().forEach((track) => track.stop());
    setVideoStream(null);
    setAudioStream(null);
    setSessionId(null);
    setConnectionState("disconnected");
  }, [audioStream, videoStream]);

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
          avatar: "huang_xuhua",
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
      setSessionId(answer.sessionid == null ? null : String(answer.sessionid));
    } catch (cause) {
      peer.close();
      peerRef.current = null;
      setConnectionState("failed");
      setError(cause instanceof Error ? cause.message : "数字人连接失败");
    }
  }, []);

  useEffect(() => () => peerRef.current?.close(), []);

  return {
    connectionState,
    sessionId,
    videoStream,
    audioStream,
    error,
    connect,
    disconnect,
  };
}
