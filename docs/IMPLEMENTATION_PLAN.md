# Demo 实施计划

## 目标

先搭建不依赖 GPU 的前后端闭环，再逐步接入线上 ASR、LLM、流式 TTS 和 MuseTalk。每个外部能力都通过接口隔离，避免更换供应商或数字人模型时修改主流程。

## 模块划分

```text
frontend
├─ 会话状态机
├─ 字幕和调试消息
├─ 文本输入（第一阶段）
├─ 麦克风权限（第二阶段接音频上传）
└─ WebRTC播放器（接MuseTalk时启用）

backend
├─ API / WebSocket入口
├─ SessionManager：会话和当前轮次
├─ ConversationOrchestrator：链路编排
├─ ASRProvider：语音转文字
├─ LLMProvider：流式回复
├─ TTSProvider：流式音频
└─ AvatarEngine：数字人音频和中断接口
```

## 分步实施

### 阶段 1：Mock 闭环（当前）

- 创建和删除会话。
- WebSocket连接、状态事件和字幕事件。
- 输入文字后模拟LLM流式回复。
- 模拟TTS音频分片和数字人处理。
- 支持中断当前回答。
- 展示首段回复与整轮耗时。

验收：不需要API Key和GPU，浏览器能够完整走通一轮模拟对话。

### 阶段 2：接入真实 LLM

- 实现OpenAI兼容的流式LLM Provider。
- 增加超时、取消、错误事件和有限重试。
- 实现中文短句切分，短句达到阈值后立即送TTS。

注意：API Key只能保存在后端；记录首Token和首个可播短句时间。

### 阶段 3：接入真实流式 TTS

- 选择支持真正流式输出的云TTS。
- 将音频统一为单声道PCM，并建立带时间戳的音频分片。
- 先在浏览器播放语音，不接MuseTalk。
- 验证分句边界是否出现爆音、重音或停顿异常。

注意：不能等完整音频文件生成；中断必须同时取消云端请求和本地队列。

### 阶段 4：接入流式 ASR

- 浏览器采集麦克风，启用AEC、降噪和自动增益。
- 音频通过WebSocket发送到后端。
- 接入流式ASR中间结果和最终结果。
- 增加VAD结束判断和热词配置。

注意：数字人播放期间仍要允许用户插话，但必须避免扬声器声音被ASR重新识别。

### 阶段 5：接入 LiveTalking + MuseTalk

- 独立部署GPU Worker。
- 完成固定人物视频预处理和模型预热。
- 将TTS PCM分片推送给AvatarEngine。
- 通过WebRTC输出720p/25 FPS H.264音视频。
- 以音频为主时钟做口型同步和过期视频帧丢弃。

注意：先用固定WAV证明MuseTalk稳定25 FPS，再进入实时链路。

### 阶段 6：三秒延迟和稳定性

- 给VAD、ASR、LLM、TTS、MuseTalk和WebRTC分别埋点。
- 优化首段文本切分、TTS首包和初始播放缓冲。
- 验证用户打断、网络断线和云API失败恢复。
- 连续运行2小时，检查显存和内存是否持续增长。

验收：P95开口延迟小于3秒，音画偏差不超过120ms，打断约300ms内生效。

## Demo 阶段暂不实现

- 多租户和复杂权限系统。
- 多数字人并发调度。
- Kubernetes和自动扩缩容。
- 数据库持久化会话历史。
- 复杂运营后台和计费系统。
- 本地ASR、LLM、TTS模型。

## 开发约束

- Python 固定为 3.12，后端统一使用 `uv`、`pyproject.toml` 和 `uv.lock` 管理环境。
- 所有流数据携带 `sessionId`、`turnId` 和递增序号。
- 新一轮输入会取消上一轮尚未完成的任务。
- Provider层不能依赖FastAPI或前端数据结构。
- 云API密钥不写入代码和Git。
- 先锁定可运行依赖版本，再考虑升级。
- 日志不得记录API Key和完整敏感音频。
