# EmbyCheckin - Telegram 自动签到调度器

使用可选 AI 提供方（OpenAI / Gemini / Claude）自动识别验证码，完成 Telegram 机器人签到。

## 功能

- **多任务管理**：支持同时管理多个签到任务
- **多账号支持**：管理多个 Telegram 账号
- **Web UI 管理界面**：可视化任务配置与监控
- **灵活的任务类型**：支持 `bot_checkin`（机器人签到）、`send_message`（消息发送）、`emby_keepalive`（Emby 保活）、`exam_assistant`（考核辅助）
- **Cron 表达式调度**：灵活配置执行时间
- **执行日志**：完整的任务执行历史记录
- **AI 验证码识别**：支持 OpenAI / Gemini / Claude

## 快速开始

### 方式一：使用预构建镜像（推荐）

```bash
# 1. 下载 docker-compose.yml
wget https://raw.githubusercontent.com/ZJ145013/EmbyCheckin/main/docker-compose.yml

# 2. 创建 .env 文件配置 AI API Key
echo "GEMINI_API_KEY=your_api_key" > .env

# 3. 启动
docker-compose up -d

# 4. 访问 Web UI
# http://127.0.0.1:8765/
```

### 方式二：本地构建

```bash
# 1. 克隆仓库
git clone https://github.com/ZJ145013/EmbyCheckin.git
cd EmbyCheckin

# 2. 创建 .env 文件配置 AI API Key
echo "GEMINI_API_KEY=your_api_key" > .env

# 3. 构建并启动
docker-compose up --build -d

# 4. 访问 Web UI
# http://127.0.0.1:8765/
```

### 方式三：可视化配置器

适用于 Mac / Windows / Ubuntu。通过浏览器填写表单，自动生成 `.env` 与 `docker-compose.yml`。

```bash
# 1. 克隆仓库
git clone https://github.com/ZJ145013/EmbyCheckin.git
cd EmbyCheckin

# 2. 启动配置器
python3 tools/config_ui.py

# 3. 打开浏览器访问 http://127.0.0.1:8765/
# 按页面提示生成配置文件

# 4. 启动服务
docker-compose up -d
```

## 配置说明

编辑 `.env` 文件或直接修改 `docker-compose.yml`：

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `DB_PATH` | 数据库路径 | `data/scheduler.db` |
| `BIND_HOST` | Web 服务绑定地址 | `0.0.0.0` |
| `BIND_PORT` | Web 服务端口 | `8765` |
| `API_ID` | Telegram API ID | `2040` |
| `API_HASH` | Telegram API Hash | (内置) |
| `AI_PROVIDER` | AI 提供方 (openai/gemini/claude) | `gemini` |
| `AI_SSL_VERIFY` | TLS 证书校验 | `true` |

### OpenAI 配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `OPENAI_BASE_URL` | API 地址 | `https://api.openai.com/v1` |
| `OPENAI_API_KEY` | API 密钥 | 需配置 |
| `OPENAI_MODEL` | 模型 | `gpt-4o-mini` |

### Gemini 配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `GEMINI_BASE_URL` | API 地址 | Google 官方 |
| `GEMINI_API_KEY` | API 密钥 | 需配置 |
| `GEMINI_MODEL` | 模型 | `gemini-2.5-flash` |

### Claude 配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `CLAUDE_BASE_URL` | API 地址 | `https://api.anthropic.com` |
| `CLAUDE_API_KEY` | API 密钥 | 需配置 |
| `CLAUDE_MODEL` | 模型 | `claude-3-5-sonnet-20241022` |
| `CLAUDE_MAX_TOKENS` | 最大输出 token 数 | `200` |

## 任务类型

| 类型 | 说明 |
|------|------|
| `bot_checkin` | 机器人签到（支持 AI 验证码识别） |
| `send_message` | 简单消息发送（保活用） |
| `emby_keepalive` | Emby 保活（模拟播放视频保持账号活跃） |
| `exam_assistant` | 考核辅助（监控群消息用 AI 自动回答问题） |

详细任务配置示例请参考 [docs/task-config-examples.md](docs/task-config-examples.md)。

## 常用命令

```bash
# 启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down

# 更新镜像
docker-compose pull && docker-compose up -d

# 重新构建
docker-compose up --build -d
```

## 目录结构

```
EmbyCheckin/
├── Dockerfile              # Docker 镜像
├── docker-compose.yml      # Docker 部署配置
├── tools/
│   └── config_ui.py        # 可视化配置器
├── embycheckin/            # 调度器模块
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

## 故障排除

### Apple Silicon（M1/M2/M3）报错 no matching manifest

预构建镜像仅提供 `linux/amd64`。解决方式：

1. 使用仿真运行：`docker-compose up -d`（已在 compose 中配置 platform）
2. 或本地构建：`docker-compose up --build -d`

### 登录失败
- 在 Web UI 中添加账号时，确认手机号格式正确（带国际区号，如 `+86`）
- 确认 Telegram 客户端能收到验证码

### 签到失败
- 查看日志：`docker-compose logs -f`
- 检查 AI API 是否正常
- 确认已加入目标群组并关注机器人

### Session 失效
- 在 Web UI 中删除对应账号
- 重新添加账号并登录

## License

MIT
