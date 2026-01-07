# EmbyCheckin - Telegram 自动签到工具

使用可选 AI 提供方（OpenAI / Gemini / Claude）自动识别验证码，完成 Telegram 机器人签到。

## 功能

- 自动识别图片验证码
- 每日定时签到
- 支持 Docker 部署
- 日志记录
- 支持选择 AI 提供方（OpenAI / Gemini / Claude）

### 新版调度器 (v2.0)

- **多任务管理**：支持同时管理多个签到任务
- **多账号支持**：管理多个 Telegram 账号
- **Web UI 管理界面**：可视化任务配置与监控
- **灵活的任务类型**：支持 `bot_checkin`（机器人签到）、`send_message`（消息发送）、`emby_keepalive`（Emby 保活）、`exam_assistant`（考核辅助）
- **Cron 表达式调度**：灵活配置执行时间
- **执行日志**：完整的任务执行历史记录

## 快速开始

### 方式零：可视化配置器（推荐给小白）

适用于 Mac / Windows / Ubuntu。通过浏览器填写表单，自动生成 `.env`（含密钥）与 `docker-compose.yml`，无需手动编辑 YAML。

```bash
# 1. 克隆仓库
git clone https://github.com/ZJ145013/EmbyCheckin.git
cd EmbyCheckin

# 2. 启动配置器（零第三方依赖）
python3 tools/config_ui.py

# 3. 打开浏览器访问
# http://127.0.0.1:8765/
# 按页面提示生成 .env + docker-compose.yml

# 4. 首次登录（交互式）
docker compose run -it terminus-checkin

# 5. 后台运行
docker compose up -d
```

## Docker 集成配置器（首次部署模式）

镜像内已集成可视化配置器，并在容器启动时自动检查配置：

- 如果检测到配置缺失/明显不正确：不会执行签到，会自动启动配置页面（用于第一次部署）。
- 配置齐全：正常运行签到逻辑。

### 如何访问配置页面（推荐安全方式）

默认端口为 `8765`，并建议仅绑定本机（compose 默认是 `127.0.0.1:8765:8765`）。

- 本机/同机访问：打开 `http://127.0.0.1:8765/`
- VPS 远程访问（推荐）：使用 SSH 端口转发

```bash
ssh -L 8765:127.0.0.1:8765 user@your-vps
# 然后在本机浏览器打开 http://127.0.0.1:8765/
```

### 在 VPS 上直接运行配置器（不推荐直接暴露公网）

如果你希望用 `http://<VPS_IP>:8765/` 直接访问（例如临时调试），需要让配置器监听 `0.0.0.0`：

```bash
python3 tools/config_ui.py --host 0.0.0.0 --port 8765
```

注意：

- 强烈建议仅在防火墙/安全组做白名单放行（只允许你自己的 IP），或仅用于内网；不要长期对公网裸露。
- 如果报 `Address already in use`，说明端口已被占用，换一个端口即可，例如 `--port 8876`。

配置生成后重启容器即可进入正常签到流程。

### 方式一：使用预构建镜像（推荐）

```bash
# 1. 下载 docker-compose.yml
wget https://raw.githubusercontent.com/ZJ145013/EmbyCheckin/main/docker-compose.yml

# 2. 编辑配置
# 修改 PHONE_NUMBER 和 GEMINI_API_KEY

# 3. 首次运行（需要交互式登录）
docker-compose run -it terminus-checkin

# 4. 登录成功后，后台运行
docker-compose up -d
```

### 方式二：本地构建

```bash
# 1. 克隆仓库
git clone https://github.com/ZJ145013/EmbyCheckin.git
cd EmbyCheckin

# 2. 编辑 docker-compose.yml，修改配置

# 3. 构建并启动
docker-compose up --build
```

## 配置说明

如果你不想手动编辑配置，优先使用上面的“方式零：可视化配置器”，它会生成 `.env + docker-compose.yml`（更适合小白且避免空值覆盖）。

编辑 `docker-compose.yml`：

```yaml
environment:
  # 首次登录需要填写手机号（带国际区号）
  - PHONE_NUMBER=+861**********

  # AI 提供方选择：openai / gemini / claude
  - AI_PROVIDER=openai

  # OpenAI（或 OpenAI 兼容接口）配置（AI_PROVIDER=openai）
  - OPENAI_BASE_URL=https://api.openai.com/v1
  - OPENAI_API_KEY=your_openai_api_key
  - OPENAI_MODEL=gpt-4o-mini
  # （可选）OpenAI 兼容网关：SSE 流式
  # - OPENAI_USE_STREAM=false
  # - OPENAI_STREAM_INCLUDE_USAGE=true
  # （可选）部分模型参数（按需开启）
  # - OPENAI_REASONING_EFFORT=low
  # - OPENAI_VERBOSITY=medium

  # Gemini 官方 REST API 配置（AI_PROVIDER=gemini）
  - GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
  - GEMINI_API_KEY=your_gemini_api_key
  - GEMINI_MODEL=gemini-2.5-flash
  # （可选）Gemini 鉴权与端点兼容（第三方网关/镜像站常用）
  # - GEMINI_API_KEY_MODE=header  # query/header/both（默认 header）
  # - GEMINI_USE_STREAM=false     # true 时调用 :streamGenerateContent?alt=sse 并解析 SSE（默认 false）

  # （可选）TLS/证书：企业代理/自签证书场景（建议优先配置 CA，而不是关闭校验）
  # 全局（对 OpenAI/Gemini/Claude 均生效）
  - AI_SSL_VERIFY=true
  - AI_CA_FILE=/path/to/ca.pem
  - AI_CA_DIR=/path/to/certs
  # 单提供方覆盖（例如 Gemini）
  - GEMINI_SSL_VERIFY=true
  - GEMINI_CA_FILE=/path/to/ca.pem
  - GEMINI_CA_DIR=/path/to/certs

  # Claude（Anthropic）配置（AI_PROVIDER=claude）
  - CLAUDE_BASE_URL=https://api.anthropic.com
  - CLAUDE_API_KEY=your_claude_api_key
  - CLAUDE_MODEL=claude-3-5-sonnet-20241022
  # （可选）Claude 兼容网关：SSE 流式、请求头与 thinking
  # - CLAUDE_USE_STREAM=false
  # - CLAUDE_MAX_TOKENS=100
  # - CLAUDE_THINKING_ENABLED=false
  # - CLAUDE_THINKING_BUDGET_TOKENS=1024

  # 签到时间（24小时制）
  - CHECKIN_HOUR=9
  - CHECKIN_MINUTE=0

  # 启动时是否立即签到
  - RUN_NOW=false
```

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `API_ID` | Telegram API ID | `2040` |
| `API_HASH` | Telegram API Hash | (内置) |
| `PHONE_NUMBER` | 手机号（首次登录需要） | 空 |
| `AI_PROVIDER` | AI 提供方 | `openai` |
| `OPENAI_BASE_URL` | OpenAI/兼容接口地址 | `https://api.openai.com/v1` |
| `OPENAI_API_KEY` | OpenAI/兼容接口密钥 | 需配置 |
| `OPENAI_MODEL` | OpenAI/兼容接口模型 | `gpt-4o-mini` |
| `OPENAI_USE_STREAM` | OpenAI 是否使用 SSE 流式接口 | `false` |
| `OPENAI_STREAM_INCLUDE_USAGE` | SSE 是否附带 usage | `true` |
| `OPENAI_REASONING_EFFORT` | （可选）推理强度 | 空 |
| `OPENAI_VERBOSITY` | （可选）输出冗长度 | 空 |
| `GEMINI_BASE_URL` | Gemini REST API 地址 | Google 官方 |
| `GEMINI_API_KEY` | Gemini API 密钥 | 需配置 |
| `GEMINI_MODEL` | Gemini 模型 | `gemini-2.5-flash` |
| `GEMINI_API_KEY_MODE` | Gemini API Key 传递方式 | `header` |
| `GEMINI_USE_STREAM` | Gemini 是否使用 SSE 流式接口 | `false` |
| `AI_SSL_VERIFY` | TLS 证书校验开关（全局） | `true` |
| `AI_CA_FILE` | 自定义 CA 文件（全局） | 空 |
| `AI_CA_DIR` | 自定义 CA 目录（全局） | 空 |
| `OPENAI_SSL_VERIFY` | TLS 证书校验开关（OpenAI） | 继承 `AI_SSL_VERIFY` |
| `OPENAI_CA_FILE` | 自定义 CA 文件（OpenAI） | 继承 `AI_CA_FILE` |
| `OPENAI_CA_DIR` | 自定义 CA 目录（OpenAI） | 继承 `AI_CA_DIR` |
| `GEMINI_SSL_VERIFY` | TLS 证书校验开关（Gemini） | 继承 `AI_SSL_VERIFY` |
| `GEMINI_CA_FILE` | 自定义 CA 文件（Gemini） | 继承 `AI_CA_FILE` |
| `GEMINI_CA_DIR` | 自定义 CA 目录（Gemini） | 继承 `AI_CA_DIR` |
| `CLAUDE_SSL_VERIFY` | TLS 证书校验开关（Claude） | 继承 `AI_SSL_VERIFY` |
| `CLAUDE_CA_FILE` | 自定义 CA 文件（Claude） | 继承 `AI_CA_FILE` |
| `CLAUDE_CA_DIR` | 自定义 CA 目录（Claude） | 继承 `AI_CA_DIR` |
| `CLAUDE_BASE_URL` | Claude API 地址 | `https://api.anthropic.com` |
| `CLAUDE_API_KEY` | Claude API 密钥 | 需配置 |
| `CLAUDE_MODEL` | Claude 模型 | `claude-3-5-sonnet-20241022` |
| `CLAUDE_USE_STREAM` | Claude 是否使用 SSE 流式接口 | `false` |
| `CLAUDE_MAX_TOKENS` | Claude 最大输出 token 数 | `100` |
| `CLAUDE_THINKING_ENABLED` | 是否启用 thinking 字段 | `false` |
| `CLAUDE_THINKING_BUDGET_TOKENS` | thinking 预算 token 数 | `1024` |
| `CHECKIN_HOUR` | 签到时间（小时） | `9` |
| `CHECKIN_MINUTE` | 签到时间（分钟） | `0` |
| `RUN_NOW` | 启动时立即签到 | `false` |

> 兼容说明：历史版本用 `GEMINI_BASE_URL/GEMINI_API_KEY/GEMINI_MODEL` 走 OpenAI 兼容的 `/chat/completions` 接口。本版本在 `AI_PROVIDER=openai` 时仍会在 `OPENAI_*` 未配置的情况下回退使用旧变量，但建议尽快切换到 `OPENAI_*` 以避免语义混淆。
>
> TLS 提示：如果你把 `GEMINI_BASE_URL` 指向第三方网关/镜像站，且遇到 `certificate verify failed: self-signed certificate`，请优先配置 `*_CA_FILE/*_CA_DIR` 注入其 CA 证书链；仅在你明确知晓风险时再设置 `*_SSL_VERIFY=false` 关闭校验（不推荐）。
>
> 网关提示：本文默认“网关遵循官方协议，仅 BASE_URL 不同”。若你使用的网关额外校验来源请求头，可再按需设置 `OPENAI_HTTP_REFERER/OPENAI_X_TITLE/OPENAI_USER_AGENT`、`GEMINI_HTTP_REFERER/GEMINI_X_TITLE/GEMINI_USER_AGENT`、`CLAUDE_HTTP_REFERER/CLAUDE_X_TITLE/CLAUDE_USER_AGENT`。

## 常用命令

```bash
# 首次登录（交互式）
docker-compose run -it terminus-checkin

# 后台运行
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down

# 更新镜像
docker-compose pull && docker-compose up -d
```

## 离线测试验证码识别（不消耗签到机会）

当你已经在 Telegram 里拿到了验证码图片，但不想冒险点错按钮时，可以先把验证码图片保存到本地（截图或下载原图），然后用下面命令离线测试识别结果：

```bash
# 先安装最小依赖（离线测试不需要安装 Pyrogram）
pip install 'httpx==0.27.0' 'loguru==0.7.2'

# 直接在宿主机运行（需要安装依赖或在容器内运行）
python3 checkin.py --test-captcha \
  --image /path/to/captcha.png \
  --options '电视盒子、美女、视频网站、情趣内衣'
```

命令会输出匹配到的选项（stdout），你再回到 Telegram 手动点击对应按钮即可。

---

## 新版调度器 (v2.0) 使用指南

新版调度器提供 Web UI 管理界面，支持多任务、多账号管理。

### 快速启动

```bash
# 1. 克隆仓库
git clone https://github.com/ZJ145013/EmbyCheckin.git
cd EmbyCheckin

# 2. 创建 .env 文件配置 AI API Key
echo "GEMINI_API_KEY=your_api_key" > .env

# 3. 启动
docker-compose up -d

# 4. 访问 Web UI
# http://127.0.0.1:8765/
```

### 调度器配置

编辑 `.env` 文件或直接修改 `docker-compose.yml`：

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `DB_PATH` | 数据库路径 | `data/scheduler.db` |
| `BIND_HOST` | Web 服务绑定地址 | `0.0.0.0` |
| `BIND_PORT` | Web 服务端口 | `8000` |

AI 配置支持 OpenAI / Gemini / Claude。

### 任务类型

| 类型 | 说明 |
|------|------|
| `bot_checkin` | 机器人签到（支持 AI 验证码识别） |
| `send_message` | 简单消息发送（保活用） |
| `emby_keepalive` | Emby 保活（模拟播放视频保持账号活跃） |
| `exam_assistant` | 考核辅助（监控群消息用 AI 自动回答问题） |

详细任务配置示例请参考 [docs/task-config-examples.md](docs/task-config-examples.md)。

### 常用命令

```bash
# 启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down

# 重新构建
docker-compose up --build -d
```

---

## 目录结构

```
EmbyCheckin/
├── checkin.py              # 旧版签到主程序
├── docker_entrypoint.py    # Docker 入口
├── requirements.txt        # Python 依赖
├── Dockerfile              # 主镜像
├── Dockerfile.scheduler    # 调度器专用镜像
├── docker-compose.yml      # Docker 部署配置
├── tools/
│   └── config_ui.py        # 可视化配置器
├── embycheckin/            # 新版调度器模块
│   ├── app.py              # FastAPI 应用入口
│   ├── scheduler/          # 调度服务
│   ├── tasks/              # 任务类型实现
│   ├── telegram/           # Telegram 客户端管理
│   ├── web/                # Web UI 与 API
│   └── ai/                 # AI 提供方
├── docs/                   # 文档
├── sessions/               # Telegram session（自动创建）
├── logs/                   # 日志文件（自动创建）
└── data/                   # 调度器数据库（自动创建）
```

## 注意事项

1. **首次登录必须交互式运行**，需要输入 Telegram 验证码
2. 登录成功后 session 会持久化，之后可以后台运行
3. 签到时间会自动添加 0-30 分钟随机延迟，避免被检测
4. 日志保留 7 天，自动轮转

## 故障排除

### Apple Silicon（M1/M2/M3）报错 no matching manifest

原因：预构建镜像当前仅提供 `linux/amd64`，在 `linux/arm64/v8`（Apple Silicon）上直接拉取会失败。

解决方式（二选一）：

1. 使用 `linux/amd64` 仿真运行（最省事）  
   - `docker-compose run --platform linux/amd64 -it terminus-checkin`
2. 使用本地构建（原生架构，推荐）  
   - 按“方式二：本地构建”执行：`docker-compose up --build`

### 登录失败
- 确认手机号格式正确（带国际区号，如 `+86`）
- 确认 Telegram 客户端能收到验证码

### 签到失败
- 查看日志：`docker-compose logs -f`
- 检查 Gemini API 是否正常
- 确认已加入终点站群组并关注机器人 @EmbyPublicBot

### Session 失效
- 删除 `./sessions` 目录
- 重新配置 `PHONE_NUMBER`
- 重新登录

## License

MIT
