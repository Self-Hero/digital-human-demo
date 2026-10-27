# Demo 实施计划

## 目标

先搭建不依赖 GPU 的前后端闭环，再接入百炼端到端实时语音和 MuseTalk。原 ASR、LLM、TTS 接口仅作为备用路线。

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
├─ RealtimeAudioProvider：双向实时语音
├─ ASR/LLM/TTS Provider：备用路线
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

### 阶段 2：接入百炼端到端实时语音

- 实现 `qwen-audio-3.0-realtime-plus` WebSocket Provider。
- 浏览器发送麦克风音频，后端转发实时回复音频。
- 解析用户字幕、助手字幕、回复开始和结束事件。
- 增加连接超时、取消、错误事件和有限重连。

注意：API Key只能保存在后端；记录连接时间和首段回复音频时间。

### 阶段 3：接入 LiveTalking + MuseTalk

- 独立部署GPU Worker。
- 完成固定人物视频预处理和模型预热。
- 将实时模型返回的音频分片推送给AvatarEngine。
- 通过WebRTC输出720p/25 FPS H.264音视频。
- 以回复音频为主时钟做口型同步和过期视频帧丢弃。

注意：先用固定WAV证明MuseTalk稳定25 FPS，再进入实时链路。

### 阶段 4：麦克风、AEC和打断

- 浏览器采集麦克风，启用AEC、降噪和自动增益。
- 音频通过WebSocket发送到后端。
- 接入百炼服务端VAD和字幕事件。
- 用户插话时取消云端回复、音频队列和旧视频帧。

注意：数字人播放期间仍要允许用户插话，但必须避免扬声器声音被ASR重新识别。

### 阶段 5：三秒延迟和稳定性

- 给麦克风上行、百炼首段回复音频、MuseTalk和WebRTC分别埋点。
- 优化服务端VAD、回复音频首包和初始播放缓冲。
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
