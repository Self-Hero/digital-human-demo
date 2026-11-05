# 一键部署

脚本目标是从干净的 Ubuntu 22.04 GPU 服务器部署当前项目，不修改 NVIDIA 驱动。默认
实时栈只包含 LiveTalking、MuseTalk 和可选 GFPGAN，不安装 SoulX、LivePortrait 或 CodeFormer。

## 前置条件

- NVIDIA 驱动已经可用，`nvidia-smi` 能识别 RTX 4090
- `/data` 已挂载并且至少剩余 30GB（当前 100GB 数据盘足够）
- 当前项目放在服务器的 `/data/digital-human-demo`
- 云安全组已开放 `22/tcp`、`9000/tcp`，以及服务器
  `cat /proc/sys/net/ipv4/ip_local_port_range` 显示的 UDP 范围

脚本不会覆盖已有的 `backend/.env`，因此豆包凭证可以安全保留。
本项目是公开仓库，可以直接通过 HTTPS 克隆，不需要 GitHub Deploy Key。LiveTalking、
模型和全部运行依赖也由脚本自动获取。

## 完整安装

首次部署先克隆公开仓库，再执行脚本：

```bash
git clone https://github.com/Self-Hero/digital-human-demo.git /data/digital-human-demo
cd /data/digital-human-demo
bash deploy/install_full_stack.sh \
  --public-ip 36.103.177.214 --public-port 9000
```

换服务器时把 `--public-ip` 改为新机器公网 IP。当前云平台限制 `80/443/8080`，因此默认使用
`9000`；云安全组必须放行 `9000/tcp`。其他平台可传入 `--public-port 80`。脚本默认使用清华 Miniconda/Conda/PyPI、
Hugging Face 镜像和 npmmirror；PyTorch CUDA wheel 仍从 PyTorch 官方源下载。下载中断后
直接执行同一条命令，pip/Hugging Face 缓存保存在 `/data/cache`，不会从头重复下载完整文件。

脚本会完成：

1. 检查 NVIDIA 驱动、磁盘和目录。
2. 安装 FFmpeg、Nginx、编译工具等 Ubuntu 包。
3. 在 `/data/miniconda3` 安装或复用 Miniconda。
4. 创建相互隔离的 `livetalking` 和 `digitalhuman` 环境。
5. 安装 PyTorch `2.9.1+cu128` 和本项目锁定版本的 LiveTalking 依赖。
6. 把 LiveTalking 锁定到已验证提交 `c7269433`。
7. 下载 MuseTalk 1.5、SD VAE、Whisper Tiny、人脸解析权重并校验关键文件。
8. 安装后端依赖、构建 React 前端并应用本项目维护的 LiveTalking 补丁。
9. 安装 systemd 服务和 Nginx 反向代理。
10. 安装默认关闭的 GFPGAN 实时运行时，并执行 CUDA、Python、模型文件、Nginx 和后端健康检查。

只安装实时推理所需权重。MuseTalk 1.0、DWPose、SyncNet 属于旧版本、训练或评估路径，
LiveTalking 的 MuseTalk 1.5 实时链路不会读取它们，因此不下载。

## 处理人物素材并启动

安装脚本不会处理人物素材，也不会启动 LiveTalking 人物实例。安装完成并上传待机视频后，
运行独立启动脚本完成预处理、前端人物 ID 配置和服务启动：

```bash
cd /data/digital-human-demo
bash deploy/start_avatar.sh \
  --avatar-source /data/source/dameng_slient2.mp4 \
  --avatar-id ma_renda_dynamic
```

默认使用 MuseTalk v1.5、`bbox_shift=-2`、`extra_margin=0` 和 `jaw` 融合方式。预处理结果
位于 `/data/LiveTalking/data/avatars/<avatar-id>`。

人物已经预处理过时，无需再传素材，直接启动或重启：

```bash
bash deploy/start_avatar.sh --avatar-id ma_renda_dynamic
```

切换人物时，脚本会停止其他占用 `8010` 端口的 LiveTalking 人物实例，然后启动指定实例。
它不会重新安装依赖或下载模型。

## 验证与日志

回复音频通过本项目维护的 `/humanpcm` WebSocket 补丁连续送入 LiveTalking。
豆包返回的 24 kHz、16 bit、单声道 PCM 会在 LiveTalking 内持续重采样为
16 kHz，并按 20 ms 帧送入 MuseTalk。每轮回答只产生一次 `start` 和一次
`end`。服务默认先缓冲 200 ms 音频，避免分块到达抖动让音频队列见底并
切回闭嘴待机状态；可通过 systemd 中的 `LIVETALKING_PCM_PREBUFFER_MS` 调整。

部署同时启用局部嘴部合成与单向时序稳定：嘴部软遮罩之外保留原始脸部，
遮罩内进行有限肤色匹配和轻量锐化，再对低运动帧抑制闪动。该处理不等待
未来帧。可通过 `LIVETALKING_MOUTH_LOCAL_COMPOSITOR`、
`LIVETALKING_MOUTH_COLOR_MATCH`、`LIVETALKING_MOUTH_SHARPEN`、
`LIVETALKING_MOUTH_STABILIZER`、`LIVETALKING_MOUTH_STRENGTH` 和
`LIVETALKING_MOUTH_MOTION_THRESHOLD` 调整或关闭。昂贵的光流对齐默认关闭；
只有明确设置 `LIVETALKING_MOUTH_OPTICAL_FLOW=1` 才会启用。

GFPGAN 实时修复运行时会随完整部署安装，但默认关闭，不加载模型也不占用显存。
设置 `LIVETALKING_GFPGAN=1` 后重启对应头像服务即可启用。实时路径直接处理
MuseTalk 已生成的批量人脸块，不运行逐帧人脸检测。默认使用 AMP、batch 2 和 0.6
融合强度；可通过 `LIVETALKING_GFPGAN_BATCH_SIZE`、
`LIVETALKING_GFPGAN_AMP`、`LIVETALKING_GFPGAN_BLEND` 调整。

单独安装或更新 GFPGAN 运行时：

```bash
bash deploy/install_gfpgan.sh
```

CodeFormer 不属于实时栈，只有明确需要离线人脸修复时才单独安装：

```bash
INSTALL_CODEFORMER=1 bash deploy/install_face_pipeline.sh
```

该命令不会安装 LivePortrait。旧版离线闭嘴中和流程同时需要两者时，必须显式设置
`INSTALL_LIVEPORTRAIT=1 INSTALL_CODEFORMER=1`；默认服务器部署不执行该流程。

建议通过 systemd drop-in 为单个头像启用，而不是修改模板：

```ini
[Service]
Environment=LIVETALKING_GFPGAN=1
```

```bash
bash deploy/bootstrap_server.sh --verify-only

sudo systemctl status digital-human-backend
sudo systemctl status livetalking@ma_renda_dynamic
sudo journalctl -u digital-human-backend -f
sudo journalctl -u livetalking@ma_renda_dynamic -f
```

公网页面默认为 `http://36.103.177.214:9000/`。普通公网 HTTP 通常无法获得浏览器麦克风权限；
完整语音联调仍需域名和可信 HTTPS。TURN 默认不部署，前后端使用 STUN；复杂网络下 ICE
失败时再按 [PUBLIC_SERVER_DEPLOYMENT.md](PUBLIC_SERVER_DEPLOYMENT.md) 增加 TURN。

## 可重复执行

脚本设计为可重复运行：已存在的 Conda 环境和完整模型会复用，Hugging Face 下载支持
续传，已有 `backend/.env` 和 `frontend/.env.production` 不会被覆盖。每次运行仍会检查
关键模型哈希，并在配置变化后重启后端和 Nginx。人物预处理和 LiveTalking 实例启动只由
`deploy/start_avatar.sh` 负责。若 LiveTalking 有未提交的代码修改，脚本
不会强制切换提交，避免覆盖人工修改。
