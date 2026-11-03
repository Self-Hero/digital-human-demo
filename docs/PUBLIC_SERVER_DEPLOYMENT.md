# 公网 GPU 服务器部署

当前 GPU 服务器：

- 公网 IP：`36.103.177.214`
- 内网 IP：`10.0.20.139`
- 系统：Ubuntu 22.04
- 数据盘：`/data`

## 地址边界

公网 IP 只用于浏览器入口和 WebRTC ICE/TURN。部署在同一台服务器上的进程继续使用
回环地址，避免绕公网、增加延迟或意外暴露内部接口：

```env
# backend -> LiveTalking
LIVETALKING_BASE_URL=http://127.0.0.1:8010

# Vite/Nginx -> backend
API_UPSTREAM=http://127.0.0.1:8001

# Vite/Nginx -> LiveTalking HTTP signaling
AVATAR_UPSTREAM=http://127.0.0.1:8010
```

开发阶段可从浏览器访问 `http://36.103.177.214:5173`。后端 CORS 示例已包含该地址。
公网 IP 上的普通 HTTP 不是浏览器安全上下文，麦克风权限可能被拒绝；完整实时语音联调应
绑定域名并通过 Nginx 或 Caddy 提供可信 HTTPS。

## STUN 与可选 TURN

服务器位于云平台 NAT 后面，aiortc 仅发布 `10.0.20.139` 时，公网浏览器无法直接连接。
首次联调先让浏览器和 LiveTalking 都使用 STUN：

```env
VITE_STUN_URL=stun:stun.freeswitch.org:3478
VITE_TURN_URL=
```

LiveTalking 启动参数保持一致：

```bash
--stun "stun:stun.freeswitch.org:3478"
```

这条链路成功时不需要 TURN。部分企业网、运营商 NAT 或严格防火墙会阻断点对点 UDP；
只有出现 ICE 连接失败或需要生产级稳定性时，才部署 coturn，并配置公网/内网映射：

```text
external-ip=36.103.177.214/10.0.20.139
listening-port=3478
min-port=49160
max-port=49200
```

coturn 可用后，前端再启用：

```env
VITE_TURN_URL=turn:36.103.177.214:3478?transport=udp
VITE_TURN_USERNAME=<turn-username>
VITE_TURN_PASSWORD=<turn-password>
VITE_TURN_FORCE_RELAY=false
```

前端设置 TURN 后仍优先使用直接连接，直连失败时再回落到 TURN。只有诊断 TURN
链路时才临时设置 `VITE_TURN_FORCE_RELAY=true`，强制所有媒体经过中继。

## 云安全组

建议只开放：

- `22/tcp`：SSH，尽量限制管理端来源 IP
- `80/tcp`、`443/tcp`：公网 Web/HTTPS 入口
- 不部署 TURN 时，临时放行 `32768-60999/udp` 用于服务器 WebRTC ICE；实际范围以
  `cat /proc/sys/net/ipv4/ip_local_port_range` 为准
- 部署 TURN 时，开放 `3478/udp`、`3478/tcp` 和配置的 relay 端口池，例如
  `49160-49200/udp`

不要直接向公网开放后端 `8001` 和 LiveTalking `8010`。由 Nginx/Caddy 将 `/api`、
`/avatar-api` 和 WebSocket 请求反向代理到本机服务。

## 目录规划

```text
/data/digital-human-demo   业务前后端
/data/LiveTalking          LiveTalking + MuseTalk
/data/livetalking-data     avatar、源视频和预处理缓存
/data/turn.env             可选 TURN 凭证，仅服务器可读
```

SoulX 保持在 `/data/SoulX-FlashHead` 和独立的 `flashhead` Conda 环境中；LiveTalking
使用独立环境，不能共用 Python 依赖。
