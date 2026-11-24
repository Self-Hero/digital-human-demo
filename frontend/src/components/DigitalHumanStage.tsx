import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Volume2, VolumeX } from "lucide-react";

import { appPath } from "../appPath";
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
  };
  onlineClients: number;
  conversationBusy: boolean;
  presenceReady: boolean;
  connectPending: boolean;
  reclaimPending: boolean;
  onReclaimConversation: () => Promise<boolean>;
}

export function DigitalHumanStage({
  state,
  metrics,
  avatar,
  onlineClients,
  conversationBusy,
  presenceReady,
  connectPending,
  reclaimPending,
  onReclaimConversation,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [mediaAspectRatio, setMediaAspectRatio] = useState(9 / 16);
  const [audioPlaybackBlocked, setAudioPlaybackBlocked] = useState(false);
  const [outputMuted, setOutputMuted] = useState(false);
  const configuredIdleImage = import.meta.env.VITE_AVATAR_IDLE_IMAGE;
  const idleImage = configuredIdleImage
    ? appPath(configuredIdleImage)
    : undefined;
  const visualState =
    avatar.connectionState === "failed"
      ? "error"
      : avatar.connectionState === "connected"
        ? state
        : "connecting";
  const statusLabel =
    avatar.connectionState === "disconnected"
      ? "等待连接数字人"
      : avatar.connectionState === "connecting"
        ? "正在连接数字人"
        : avatar.connectionState === "failed"
          ? "数字人连接异常"
          : stateLabels[state];

  const updateAspectRatio = (width: number, height: number) => {
    if (width > 0 && height > 0) setMediaAspectRatio(width / height);
  };

  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = avatar.videoStream;
  }, [avatar.videoStream]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.srcObject = avatar.audioStream;
    if (!avatar.audioStream) {
      setAudioPlaybackBlocked(false);
      return;
    }
    void audio
      .play()
      .then(() => setAudioPlaybackBlocked(false))
      .catch(() => setAudioPlaybackBlocked(true));
  }, [avatar.audioStream]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.muted = outputMuted;
  }, [outputMuted]);

  const resumeAudioPlayback = () => {
    const audio = audioRef.current;
    if (!audio) return;
    void audio
      .play()
      .then(() => setAudioPlaybackBlocked(false))
      .catch(() => setAudioPlaybackBlocked(true));
  };

  const stageStyle = {
    "--avatar-aspect-ratio": mediaAspectRatio,
  } as CSSProperties;
  const orientation = mediaAspectRatio < 1 ? "portrait" : "landscape";
  const connectMessage = !presenceReady
    ? "正在连接交互服务"
    : conversationBusy
      ? avatar.error ?? "当前数字人正在使用，请稍后再试"
      : avatar.error ?? "数字人已就绪";
  const connectDisabled =
    !presenceReady || conversationBusy || connectPending ||
    avatar.connectionState === "connecting";

  return (
    <section
      className="stage"
      aria-label="数字人预览区"
      data-orientation={orientation}
      style={stageStyle}
    >
      <div className={`avatar-video-shell state-${visualState}`}>
        <video
          className="avatar-live-video"
          ref={videoRef}
          autoPlay
          playsInline
          muted
          onLoadedMetadata={(event) => {
            updateAspectRatio(event.currentTarget.videoWidth, event.currentTarget.videoHeight);
          }}
          onResize={(event) => {
            updateAspectRatio(event.currentTarget.videoWidth, event.currentTarget.videoHeight);
          }}
        />
        {idleImage && (
          <img
            className={`avatar-idle-image${
              avatar.playbackSpeaking || state === "speaking" ? " is-hidden" : ""
            }`}
            src={idleImage}
            alt=""
            aria-hidden="true"
            draggable={false}
            onLoad={(event) => {
              updateAspectRatio(
                event.currentTarget.naturalWidth,
                event.currentTarget.naturalHeight,
              );
            }}
            onError={(event) => {
              event.currentTarget.hidden = true;
            }}
          />
        )}
        <audio ref={audioRef} autoPlay />
        <div className="stage-shade" aria-hidden="true" />
        <header className="stage-header">
          <div className="stage-heading" aria-live="polite">
            <div className="stage-status">
              <span className={`status-dot state-${visualState}`} />
              <strong>{statusLabel}</strong>
            </div>
            <div className="service-meta">
              <span>在线 {onlineClients}</span>
              {metrics && (
                <span>
                  首段 {metrics.firstAudioMs ?? "—"} ms · 完整 {metrics.totalMs} ms
                </span>
              )}
            </div>
          </div>
          <button
            className="output-button"
            type="button"
            aria-label={outputMuted ? "开启播报声音" : "关闭播报声音"}
            aria-pressed={outputMuted}
            title={outputMuted ? "开启播报声音" : "关闭播报声音"}
            onClick={() => setOutputMuted((muted) => !muted)}
          >
            {outputMuted ? <VolumeX size={20} /> : <Volume2 size={20} />}
          </button>
        </header>
        {audioPlaybackBlocked && avatar.connectionState === "connected" && (
          <button
            className="audio-unlock-button"
            type="button"
            onClick={resumeAudioPlayback}
          >
            开启声音
          </button>
        )}
        {avatar.connectionState !== "connected" && (
          <div className="avatar-connect-panel">
            <div className="connect-copy">
              <span>实时数字人咨询</span>
              <p>{connectMessage}</p>
            </div>
            <button
              className="primary-button"
              type="button"
              onClick={avatar.connect}
              disabled={connectDisabled}
            >
              {conversationBusy
                ? "数字人使用中"
                : avatar.connectionState === "connecting" || connectPending
                  ? "连接中"
                  : "点击开始实时咨询"}
            </button>
            {conversationBusy && (
              <button
                className="reclaim-button"
                type="button"
                onClick={() => void onReclaimConversation()}
                disabled={reclaimPending}
              >
                {reclaimPending ? "正在检查" : "尝试释放闲置会话"}
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
