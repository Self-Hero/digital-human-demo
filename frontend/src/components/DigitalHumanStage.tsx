import type { SessionState, TurnMetrics } from "../types/conversation";

const stateLabels: Record<SessionState, string> = {
  connecting: "正在连接",
  idle: "等待提问",
  listening: "正在聆听",
  thinking: "正在思考",
  speaking: "正在回答",
  error: "连接异常",
};

interface Props {
  state: SessionState;
  metrics: TurnMetrics | null;
}

export function DigitalHumanStage({ state, metrics }: Props) {
  return (
    <section className="stage" aria-label="数字人预览区">
      <div className={`avatar-placeholder state-${state}`}>
        <div className="avatar-face">
          <span className="eye left" />
          <span className="eye right" />
          <span className="mouth" />
        </div>
        <p>数字人模型将在后续阶段接入</p>
      </div>
      <div className="stage-status">
        <span className={`status-dot state-${state}`} />
        <strong>{stateLabels[state]}</strong>
        {metrics && (
          <span className="metrics">
            首字 {metrics.firstDeltaMs ?? "—"} ms · 整轮 {metrics.totalMs} ms
          </span>
        )}
      </div>
    </section>
  );
}
