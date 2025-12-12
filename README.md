# 终点站 (Terminus) 自动签到

使用 Gemini Vision API 自动识别验证码，完成终点站 Telegram 机器人签到。

## 功能

- 自动识别图片验证码
- 每日定时签到
- 支持 Docker 部署
- 日志记录

## 快速开始

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

编辑 `docker-compose.yml`：

```yaml
environment:
  # 首次登录需要填写手机号（带国际区号）
  - PHONE_NUMBER=+8613800138000

  # Gemini API 配置
  - GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
  - GEMINI_API_KEY=your_gemini_api_key
  - GEMINI_MODEL=gemini-2.5-flash

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
| `GEMINI_BASE_URL` | Gemini API 地址 | Google 官方 |
| `GEMINI_API_KEY` | Gemini API 密钥 | 需配置 |
| `GEMINI_MODEL` | Gemini 模型 | `gemini-2.5-flash` |
| `CHECKIN_HOUR` | 签到时间（小时） | `9` |
| `CHECKIN_MINUTE` | 签到时间（分钟） | `0` |
| `RUN_NOW` | 启动时立即签到 | `false` |

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

## 目录结构

```
terminus-checkin/
├── checkin.py          # 主程序
├── requirements.txt    # Python 依赖
├── Dockerfile
├── docker-compose.yml
├── README.md
├── sessions/           # Telegram session（自动创建）
└── logs/               # 日志文件（自动创建）
```

## 注意事项

1. **首次登录必须交互式运行**，需要输入 Telegram 验证码
2. 登录成功后 session 会持久化，之后可以后台运行
3. 签到时间会自动添加 0-30 分钟随机延迟，避免被检测
4. 日志保留 7 天，自动轮转

## 故障排除

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
