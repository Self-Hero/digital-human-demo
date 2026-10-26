# 真人数字人实时对嘴 Demo 设计

## 当前实现状态

仓库已经包含第一阶段前后端框架：

- `frontend/`：React + TypeScript + Vite 调试界面。
- `backend/`：FastAPI、WebSocket、会话状态和中断控制。
- `backend/app/providers/`：可替换的 ASR、LLM、TTS、Avatar 接口。
- 当前使用 Mock LLM、Mock TTS 和 Mock Avatar，不需要 API Key 或 GPU。
- `docs/IMPLEMENTATION_PLAN.md`：按阶段接入真实云 API 和 MuseTalk 的实施计划。

后端本地启动：

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

前端本地启动：

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

浏览器访问 `http://localhost:5173`。当前通过文字输入验证模拟流式链路，麦克风、真实音频和数字人视频会在后续阶段接入。

## 1. 目标与范围

本阶段采用以下固定方案：

- 数字人框架：LiveTalking（原 `metahuman-stream`）
- 口型模型：MuseTalk
- GPU：单张 NVIDIA RTX 4090 24GB
- 数字人数量：1 个固定真人数字人
- ASR：线上流式语音识别 API
- LLM：线上流式大模型 API
- TTS：线上流式语音合成 API
- 输出：WebRTC，720p、25 FPS
- 性能目标：用户说完后 3 秒内数字人开始发声并出现同步口型

Demo 阶段不部署本地 ASR、LLM、TTS，不使用 Kubernetes，也不做多数字人并发。RTX 4090 专门承担 MuseTalk 推理、画面合成和视频编码。

## 2. 总体架构

```text
浏览器前端
├─ 麦克风采集、AEC 回声消除、降噪
├─ 用户字幕、数字人字幕和状态展示
├─ WebSocket：控制消息、ASR 文本、会话事件
└─ WebRTC：数字人音视频播放
             │
             ▼
API 网关 / 对话编排服务（FastAPI）
├─ 会话、turnId、取消与打断控制
├─ VAD 和音频分片
├─ 线上流式 ASR 适配器
├─ 线上流式 LLM 适配器
├─ 文本分句器
├─ 线上流式 TTS 适配器
└─ 音频队列、指标与日志
             │ 流式 PCM 音频
             ▼
LiveTalking + MuseTalk Worker
├─ 已预处理的固定数字人素材
├─ MuseTalk 模型常驻显存
├─ 音频特征和嘴部区域推理
├─ 嘴部画面合成
├─ FFmpeg/NVENC H.264 编码
└─ WebRTC 音视频输出
             │
             ▼
浏览器播放
```

音频是同步主时钟。每个音频分片必须携带 `sessionId`、`turnId` 和递增的 `sequence`；视频帧按照音频播放时间生成和发送。发生用户打断时，旧 `turnId` 的 LLM、TTS、音频队列和视频帧全部作废。

## 3. 三秒延迟设计

三秒以“用户一句话结束”到“数字人第一段声音和口型出现”为口径，建议按 P95 验收。

| 环节 | P95 预算 |
|---|---:|
| VAD 判断用户说完 | 300～600 ms |
| ASR 最终结果 | 150～350 ms |
| LLM 生成首个可播短句 | 250～700 ms |
| TTS 返回首段 PCM | 200～500 ms |
| MuseTalk 首批画面与播放缓冲 | 200～450 ms |
| WebRTC 网络与解码 | 100～250 ms |
| 目标总计 | 1.2～2.85 s |

必须满足以下工程条件：

1. ASR、LLM、TTS 都采用流式接口，不能等待完整结果。
2. LLM 输出达到自然短语即可送入 TTS。中文建议以标点为主，并在约 12～30 个汉字时允许软切分。
3. TTS 必须支持低首包延迟，优先返回 PCM；不要等待完整 MP3 文件生成。
4. TTS 音频统一转换为 MuseTalk 所需的单声道 PCM 格式，内部建议以 16 kHz 音频进入口型模型。
5. MuseTalk 模型和数字人素材必须在服务启动时加载，并常驻 GPU，不能每轮会话重新加载。
6. 数字人素材在部署前完成人脸检测、裁剪、蒙版、特征和帧缓存预处理。
7. 初始音视频缓冲控制在约 100～180 ms；以音频为主时钟，视频来不及时丢弃过期帧，不暂停音频等待画面。
8. GPU 编码使用 NVENC，避免 CPU 软件编码成为瓶颈。
9. 云 ASR、LLM、TTS 选择同一地域或网络 RTT 较低的服务。
10. 前端开启浏览器 AEC，否则数字人的扬声器声音可能再次进入 ASR。

补充指标：

- 输出：720p、25 FPS、H.264，约 2～4 Mbps
- 音画偏差：目标 ±80 ms，最大不超过 120 ms
- 用户打断：检测到有效语音后 300 ms 内停止上一轮播报
- 连续运行：Demo 验收至少连续运行 2 小时，无显存持续增长

## 4. 数字人素材要求

MuseTalk 不需要为每个人物重新训练，但每个数字人都需要做一次素材预处理。固定数字人 Demo 推荐使用待机视频，而不是只用一张照片。

### 推荐素材

- 一段 20～60 秒、可循环的真人待机视频
- 原始视频建议 1080p，最终输出先使用 720p
- 固定 25 FPS，恒定帧率，不要使用可变帧率
- H.264 MP4 或无损/高码率中间格式
- 正脸或轻微侧脸，头部运动幅度小
- 嘴巴、下巴和双颊无遮挡
- 光照、曝光、白平衡稳定
- 背景固定，镜头固定，不缩放、不切镜头
- 人物可自然眨眼、呼吸和轻微点头
- 待机素材中尽量闭嘴，不要持续说话
- 服装、发型、妆容在整段视频中保持一致

### 不建议的素材

- 大幅转头、快速肢体动作或频繁遮挡嘴部
- 手持抖动、自动对焦反复变化
- 强逆光、闪烁灯光、明显美颜漂移
- 多人画面、嘴部过小或分辨率过低
- 已经强压缩并出现块状噪声的视频
- 包含镜头剪辑、字幕或水印覆盖面部的视频

还需要确认肖像权、声音权、素材版权和数字人用途授权。生产环境应保存人物授权记录，并对生成内容增加适当标识。

## 5. 硬件与基础环境

### Demo 推荐配置

| 资源 | 最低建议 | 推荐配置 |
|---|---|---|
| GPU | RTX 4090 24GB | RTX 4090 24GB，模型独占 |
| CPU | 12 核 / 24 线程、支持 AVX2 | 16 核左右的现代 Ryzen 9、Core i9 或同级服务器 CPU |
| 内存 | 32GB | 64GB |
| 系统盘 | 500GB NVMe SSD | 1TB NVMe SSD |
| 数据盘 | 可与系统盘共用 | 额外 1TB NVMe，用于素材、缓存、日志和录制文件 |
| 网络 | 稳定公网，50 Mbps 上行 | 100 Mbps 以上对称带宽；机房内千兆网络 |
| 电源 | 取决于整机 | 高品质 1000W～1200W，按显卡与 CPU 峰值核算 |

磁盘空间建议预留：

- 代码、容器镜像和 Python/CUDA 环境：50～100GB
- MuseTalk 权重及相关模型缓存：按目标版本预留 30～80GB
- 数字人原始素材和预处理缓存：每个形象预留 10～30GB
- 日志、临时音频、测试录制：至少 100GB，并设置定期清理策略

### 软件环境

- Ubuntu 22.04 LTS 优先
- NVIDIA 驱动、CUDA、PyTorch 版本严格按所选 MuseTalk/LiveTalking 提交的要求锁定
- Docker + NVIDIA Container Toolkit；若上游镜像不稳定，可先使用 Python 虚拟环境验证
- FFmpeg，确认已启用 `h264_nvenc`
- Python 3.10 优先，具体版本服从项目依赖文件
- Nginx 或 Caddy，用于 HTTPS、WebSocket 和 WebRTC 入口
- 公网 HTTPS 域名；浏览器麦克风权限通常要求安全上下文
- 跨 NAT 或公网复杂网络时部署 coturn

不要在验证前盲目升级 CUDA、PyTorch 或 TensorRT。先固定一个可工作的版本组合，再保存镜像和依赖锁文件。

## 6. 前端方案

推荐 React + TypeScript，也可以先复用 LiveTalking 自带页面验证链路，再开发业务界面。

前端职责：

- 获取麦克风权限，启用 `echoCancellation`、`noiseSuppression`、`autoGainControl`
- 建立 WebSocket 控制通道和 WebRTC 播放通道
- 展示用户实时识别字幕、数字人回复字幕和连接状态
- 发送开始会话、停止、打断、重连等控制消息
- 播放服务端返回的数字人音视频，不在浏览器端运行 MuseTalk
- 统计前端首帧、首音频、卡顿和断线重连时间

建议状态机：

```text
idle → listening → thinking → speaking
  ▲        │            │         │
  └────────┴── interrupt/recover ──┘
```

## 7. 后端方案

### 服务拆分

Demo 阶段同一台服务器部署，但保持逻辑进程分离：

1. `web`：前端静态资源和反向代理。
2. `api-orchestrator`：FastAPI，会话、鉴权、ASR/LLM/TTS 适配、分句、取消和日志。
3. `livetalking`：WebRTC 会话、音视频队列和 Avatar 接口。
4. `musetalk-worker`：模型常驻显存，单数字人串行消费音频任务。
5. `coturn`：需要公网穿透时启用。
6. `redis`：Demo 可选；如果所有服务单机运行，可先以内存状态实现，但接口中仍保留 `sessionId` 和 `turnId`。

推荐内部接口：

```text
POST /api/sessions
WS   /api/sessions/{sessionId}/audio
POST /api/sessions/{sessionId}/interrupt
GET  /api/sessions/{sessionId}/events
POST /internal/avatar/start
POST /internal/avatar/audio
POST /internal/avatar/stop
GET  /internal/avatar/health
```

线上模型供应商通过适配器隔离：

```text
StreamingASR.transcribe(audio_stream)
StreamingLLM.generate(messages, cancel_token)
StreamingTTS.synthesize(text_chunks, cancel_token)
```

这样后续更换阿里、火山、腾讯、讯飞或其他兼容服务时，不需要修改 MuseTalk 和前端。

### 队列与背压

- 每次回答创建新的 `turnId`。
- LLM 文本、TTS 音频和视频帧都绑定同一个 `turnId`。
- TTS 音频队列只允许保留少量未来音频，建议不超过 1～2 秒，避免打断迟钝。
- GPU Worker 只处理当前有效轮次；检测到取消后立即丢弃旧任务。
- 音频播放进度是主时钟，视频帧按时间戳匹配。
- 云 API 超时应快速失败并返回可理解的前端状态，不允许无限重试。

## 8. 模型部署方案

### 本机部署

仅部署：

- LiveTalking
- MuseTalk 模型及权重
- 人脸检测、音频特征、合成等 MuseTalk 依赖
- FFmpeg/NVENC 编码
- 固定数字人的预处理缓存

启动流程：

```text
加载数字人缓存
→ 加载 MuseTalk 及依赖模型到显存
→ 预热 2～3 段测试音频
→ 验证实际推理 FPS 高于 25
→ 对外开放健康检查和 WebRTC 会话
```

### 线上服务

- ASR 必须支持实时音频上传和中间/最终识别结果。
- LLM 必须支持 SSE 或 WebSocket 流式输出。
- TTS 必须支持流式合成和低首包延迟，优先 PCM 输出。
- 三类服务尽量选择相同地域，并分别记录首包、完整请求、错误率和限流指标。
- API Key 只保存在后端密钥管理或环境变量中，绝不能下发浏览器。

### 供应商选择验收表

不要只比较单价，至少实测：

| 服务 | 必测项目 |
|---|---|
| ASR | 中文准确率、流式首结果、最终结果延迟、热词、噪声环境、断线重连 |
| LLM | 首 Token、首个完整短句、并发限制、上下文长度、取消请求是否及时生效 |
| TTS | 首段 PCM 延迟、是否真正流式、音质、停顿自然度、可否立即取消、采样率 |

## 9. 开源项目地址

- LiveTalking：<https://github.com/lipku/LiveTalking>
- 原 metahuman-stream 地址（若仓库已重命名通常会自动跳转）：<https://github.com/lipku/metahuman-stream>
- MuseTalk：<https://github.com/TMElyralab/MuseTalk>
- aiortc（Python WebRTC）：<https://github.com/aiortc/aiortc>
- coturn（TURN/STUN）：<https://github.com/coturn/coturn>
- FastAPI：<https://github.com/fastapi/fastapi>
- FFmpeg：<https://github.com/FFmpeg/FFmpeg>
- Silero VAD：<https://github.com/snakers4/silero-vad>
- WebRTC VAD Python 封装：<https://github.com/wiseman/py-webrtcvad>
- FunASR（未来需要本地 ASR 时的备选）：<https://github.com/modelscope/FunASR>
- CosyVoice（未来需要本地 TTS 时的备选）：<https://github.com/FunAudioLLM/CosyVoice>

正式采用前必须逐项核对代码许可证、模型权重许可证、人物素材授权和商业使用条款。代码开源不代表模型权重、训练数据和演示素材可以直接商用。

## 10. 实施顺序

### 第 1 步：离线性能验证

- 部署 MuseTalk 并下载权重。
- 准备一个合规的固定真人待机视频。
- 完成素材预处理，输入本地 WAV，验证口型、身份稳定性和 25 FPS。
- 记录 GPU 显存、GPU 利用率、推理 FPS、编码 FPS 和温度。

### 第 2 步：LiveTalking 与 WebRTC

- 接入处理后的数字人素材。
- 浏览器稳定播放 720p/25 FPS 音视频。
- 验证公网 HTTPS、WebRTC 和必要的 TURN 回落。

### 第 3 步：线上 TTS

- 先用固定文本测试流式 TTS 到口型的完整链路。
- 重点测 TTS 首包、音画同步、分片边界爆音和打断。

### 第 4 步：线上 LLM 和 ASR

- 接入流式 LLM 和分句器。
- 最后接入流式 ASR、VAD、AEC 和用户打断。
- 端到端压测 P50、P95 和失败率。

### 第 5 步：Demo 验收

- 20 轮连续对话均可正常开始和打断。
- P95 开口延迟小于 3 秒。
- 稳定 720p/25 FPS。
- 音画偏差不超过 120 ms。
- 连续运行 2 小时无进程崩溃和显存持续增长。
- 云服务异常时界面能明确提示并恢复下一轮会话。

## 11. 当前方案边界

单张 RTX 4090、一个数字人足够用于 Demo 和单路验证，但不能据此承诺生产并发量。正式上线前必须基于最终人物素材、MuseTalk 版本、分辨率、编码参数和服务器 CPU 做实测。未来扩容时应把 `musetalk-worker` 做成独立 GPU 节点，按“同时处于说话状态的会话数”扩容，而不是按在线连接数简单估算。
