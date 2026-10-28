import { useEffect, useRef } from "react";

import type { AvatarConnectionState } from "../hooks/useAvatarSession";
import type { SessionState, TurnMetrics } from "../types/conversation";

const stateLabels: Record<SessionState, string> = {
  connecting: "正在连接",
  idle: "等待开启麦克风",
  listening: "正在聆听",
  thinking: "正在思考",
  speaking: "正在回答",
  error: "连接异常",
};

interface Props {
  state: SessionState;
  metrics: TurnMetrics | null;
  avatar: {
    connectionState: AvatarConnectionState;
    sessionId: string | null;
    videoStream: MediaStream | null;
    audioStream: MediaStream | null;
    playbackSpeaking: boolean;
    error: string | null;
    connect: () => Promise<void>;
    disconnect: () => void;
  };
}

export function DigitalHumanStage({ state, metrics, avatar }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const idleImage = import.meta.env.VITE_AVATAR_IDLE_IMAGE ?? "/avatar-idle.jpg";

  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = avatar.videoStream;
  }, [avatar.videoStream]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.srcObject = avatar.audioStream;
  }, [avatar.audioStream]);

  return (
    <section className="stage" aria-label="数字人预览区">
      <div className={`avatar-video-shell state-${state}`}>
        <video className="avatar-live-video" ref={videoRef} autoPlay playsInline muted />
        <img
          className={`avatar-idle-image${avatar.playbackSpeaking ? " is-hidden" : ""}`}
          src={idleImage}
          alt=""
          aria-hidden="true"
          draggable={false}
          onError={(event) => {
            event.currentTarget.hidden = true;
          }}
        />
        <audio ref={audioRef} autoPlay />
        {avatar.connectionState !== "connected" && (
          <div className="avatar-connect-panel">
            <p>{avatar.error ?? "数字人视频尚未连接"}</p>
            <button
              className="primary-button"
              type="button"
              onClick={avatar.connect}
              disabled={avatar.connectionState === "connecting"}
            >
              {avatar.connectionState === "connecting" ? "连接中" : "连接数字人"}
            </button>
          </div>
        )}
      </div>
      <div className="stage-status">
        <span className={`status-dot state-${state}`} />
        <strong>{stateLabels[state]}</strong>
        {avatar.connectionState === "connected" && (
          <span className="avatar-session">数字人媒体已连接</span>
        )}
        {metrics && (
          <span className="metrics">
            首段音频 {metrics.firstAudioMs ?? "—"} ms · 完整响应 {metrics.totalMs} ms
          </span>
        )}
      </div>
    </section>
  );
}
