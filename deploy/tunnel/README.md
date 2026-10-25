# SSH 隧道 + Caddy 反代

AutoDL 不提供公网 HTTP 地址；这个包在**你自己的公网主机**上跑两个现成镜像：

- `jnovack/autossh`：`ssh -L 0.0.0.0:6006:127.0.0.1:6006`，把 AutoDL 上的 `mmax-api` 拉到本机；
- `caddy:2`：TLS + SSE 反代，对外只开 80/443。

```text
公网客户端
   │ https://api.example.com
   ▼
你的公网主机
   ├── caddy:2          ← TLS / SSE
   └── jnovack/autossh  ← ssh -L
          │ outbound SSH (端口 35554)
          ▼
AutoDL 主机
   └── 127.0.0.1:6006  mmax-api
          └── 127.0.0.1:8161  Xolotl / DeepSeek
```

AutoDL 侧不需要公网入站端口，SSH 连接由你的主机主动发起。

## 准备

1. Docker + Docker Compose。
2. AutoDL 上的 `mmax-api` 已监听 `0.0.0.0:6006`（默认）。
3. 一个指向公网主机 IP 的域名（可选；没有域名就用 `:8080` 纯 HTTP）。

## 配置

```bash
cd deploy/tunnel
cp .env.example .env
# 编辑 .env：SSH_REMOTE_HOST / SSH_REMOTE_PORT / API_DOMAIN
```

生成密钥并把公钥装到 AutoDL（`ssh-copy-id` 会问一次 AutoDL 密码）：

```bash
mkdir -p keys
ssh-keygen -t ed25519 -f keys/id_ed25519 -N ""
ssh-copy-id -i keys/id_ed25519.pub -p "$SSH_REMOTE_PORT" "$SSH_REMOTE_USER@$SSH_REMOTE_HOST"
ssh-keyscan -p "$SSH_REMOTE_PORT" "$SSH_REMOTE_HOST" > keys/known_hosts
chmod 600 keys/id_ed25519
```

## 启动

```bash
docker compose up -d
docker compose logs -f tunnel   # 看到 autossh 连上即可
```

验证：

```bash
KEY="$(cat /path/to/mmax/.api_key)"   # AutoDL 上的 mmax-api Key
curl -s https://api.example.com/v1/models -H "Authorization: Bearer $KEY"
curl -s https://api.example.com/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4.1-flash-1017","messages":[{"role":"user","content":"你好"}],"stream":true}'
```

## 说明

- `SSH_MODE=-L`：本机监听、AutoDL 不监听公网；`SSH_TARGET_HOST=127.0.0.1` 是**从 AutoDL 视角**解析的 `mmax-api` 地址。
- `tunnel` 的 6006 只在 compose 网络内，不发布到宿主机；对外只有 Caddy 的 80/443。
- SSE：`flush_interval -1` + `read_timeout 0`，否则流式会被 Caddy 缓冲。
- 长思考：`mmax-api` 的 `MMAX_DEEPSEEK_TIMEOUT` 默认 1800 秒；Caddy 已设 0（不超时）。
- 鉴权：`mmax-api` 的 Bearer Key 会原样透传；需要再加一层可在 Caddyfile 里加 `basic_auth`。
- 密钥：`keys/` 已被 `.gitignore` 排除，不要把私钥提交。
- 没有域名：`.env` 里 `API_DOMAIN=:8080`，`docker-compose.yml` 的 caddy 端口加 `"8080:8080"`，用 `http://公网IP:8080` 访问（无 TLS，仅建议内网/临时）。
- AutoDL 的 SSH 端口/域名变化时，改 `.env` 后 `docker compose up -d`。

## 备选（不用第二台主机）

如果 AutoDL 能出站到 Cloudflare（已测 `trycloudflare.com` 可达），可以直接在 AutoDL 上跑：

```bash
cloudflared tunnel --url http://127.0.0.1:6006
```

会得到一个 `https://<random>.trycloudflare.com` 的临时公网地址；稳定地址需要 Cloudflare 命名隧道 + 域名。这个方案不需要 `deploy/tunnel/`，但 URL 是临时的，且中国大陆访问稳定性不如自己的公网主机。
