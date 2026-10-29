# MuseTalk 画质与切换一致性

## 原因

静音画面和说话画面必须来自同一套逐帧源图。若 `--avatar_id` 使用动嘴视频生成，
而 `--customvideo_config` 指向另一条闭嘴视频，两条视频的头部、身体动作和编码细节均
不相同。切换时做淡化只能产生重影，无法对齐姿态。

MuseTalk v1.5 只生成低分辨率的人脸区域，再放大并通过 mask 融合回原帧。融合范围过大
时，下颌、脖子和脸部纹理会显得膨胀、偏锐或缺少细节。

## 推荐结构

使用闭嘴但有自然微动作的视频生成 avatar。静音时直接使用该 avatar 的 `full_imgs`，
说话时在相同的 `full_imgs` 上生成口型。启动 LiveTalking 时不要传
`--customvideo_config`。

这样两种状态共享完全相同的分辨率、压缩来源、身体姿态和帧索引，区别仅限于口型区域。

## AutoDL 重建

在 LiveTalking 终端中整段执行：

```bash
cd /root/LiveTalking
conda activate livetalking
export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1

python -m avatars.musetalk.genavatar \
  --file /root/autodl-tmp/livetalking-data/source/feng_yucai_idle_20s_1080x1920_25fps.mp4 \
  --avatar_id feng_yucai_consistent_1080 \
  --save_path /root/autodl-tmp/livetalking-data/avatars \
  --version v15 \
  --gpu_id 0 \
  --bbox_shift -2 \
  --extra_margin 0 \
  --parsing_mode jaw
```

`extra_margin=0` 避免把更多脖子区域带入生成框；`bbox_shift=-2` 轻微扩大原始人脸上下文，
降低下半脸被放大的观感。不要覆盖原来的 avatar，便于直接回退。

## 收窄融合区域

拉取本项目最新代码后执行：

```bash
cd /root/autodl-tmp/digital-human-demo
python backend/scripts/tune_musetalk_masks.py \
  /root/autodl-tmp/livetalking-data/avatars/feng_yucai_consistent_1080 \
  --erode-px 3 \
  --opacity 0.92
```

脚本首次运行会把原 mask 备份到 `mask.original`。参数含义：

- `--erode-px 3`：把生成区域向内收 3 像素，减轻下颌和脖子变形。
- `--opacity 0.92`：保留少量原始纹理，减弱动态脸突兀的锐度和塑料感。

如口型变弱，先将 `opacity` 提高到 `0.96`；如脖子仍明显，再将 `erode-px` 提高到
`5`。每次调整都从 `mask.original` 重新计算，不会叠加破坏。

恢复原 mask：

```bash
python backend/scripts/tune_musetalk_masks.py \
  /root/autodl-tmp/livetalking-data/avatars/feng_yucai_consistent_1080 \
  --restore
```

## 启动

首次部署或 LiveTalking 代码更新后，先将 WebRTC 实际编码分辨率设为竖屏
`720x1280`：

```bash
cd /root/autodl-tmp/digital-human-demo
python backend/scripts/configure_livetalking_video.py
```

脚本会在 `/root/LiveTalking/server/webrtc.py.before-720p` 保留一份原文件备份，
并且可以重复执行。它只在视频帧进入 aiortc 编码器前缩放，不会重做
avatar 或改变 MuseTalk 推理。

如果原始待机帧和 MuseTalk 说话帧的脸部细节差异明显，可以安装静音推理开关：

```bash
cd /root/autodl-tmp/digital-human-demo
python backend/scripts/configure_livetalking_silence_inference.py
```

启动 LiveTalking 前设置 `LIVETALKING_INFER_SILENCE=1`。静音帧会使用零音频特征经过
同一套 MuseTalk 推理和 mask 融合，但音频仍然保持静音，说话状态也不变。
不设置该变量时保持 LiveTalking 原始逻辑。脚本备份原文件到
`/root/LiveTalking/avatars/base_avatar.py.before-silence-inference`。

```bash
cd /root/LiveTalking
test -e data/avatars/feng_yucai_consistent_1080 || \
  ln -s /root/autodl-tmp/livetalking-data/avatars/feng_yucai_consistent_1080 \
  data/avatars/feng_yucai_consistent_1080

set -a
source /root/autodl-tmp/turn.env
set +a
export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1

python app.py \
  --transport webrtc \
  --model musetalk \
  --avatar_id feng_yucai_consistent_1080 \
  --batch_size 4 \
  --fps 25 \
  --listenport 8010 \
  --stun "turn:36.103.236.204:3478?transport=udp"
```

这里有意省略 `--customvideo_config`。LiveTalking 在静音时会直接输出 avatar 自己的
原始帧，不会再切到另一条视频。

前端 `.env` 同步改为：

```env
VITE_AVATAR_ID=feng_yucai_consistent_1080
VITE_AVATAR_IDLE_IMAGE=
```
