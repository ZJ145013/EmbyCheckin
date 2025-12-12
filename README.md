# 终点站 (Terminus) 自动签到

使用 Gemini Vision API 自动识别验证码，完成终点站 Telegram 机器人签到。

## 功能

- 自动识别图片验证码
- 每日定时签到
- 支持 Docker 部署
- 日志记录

## 首次使用

### 1. 配置手机号

编辑 `docker-compose.yml`，填写你的手机号（带国际区号）：

```yaml
- PHONE_NUMBER=+8613800138000
```

### 2. 启动并登录

```bash
# 构建并启动
docker-compose up --build

# 首次运行会要求输入验证码
# Telegram 会发送验证码到你的 Telegram 客户端
# 在终端输入验证码完成登录
```

### 3. 登录成功后

登录成功后，session 会保存在 `./sessions` 目录。

你可以：
- 删除 `PHONE_NUMBER` 配置（或留空）
- 后台运行：`docker-compose up -d`

## 配置说明

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `API_ID` | Telegram API ID | `2040` |
| `API_HASH` | Telegram API Hash | (内置) |
| `PHONE_NUMBER` | 手机号（首次登录需要） | 空 |
| `GEMINI_BASE_URL` | Gemini API 地址 | (已配置) |
| `GEMINI_API_KEY` | Gemini API 密钥 | (已配置) |
| `GEMINI_MODEL` | Gemini 模型 | `gemini-2.5-flash` |
| `CHECKIN_HOUR` | 签到时间（小时） | `9` |
| `CHECKIN_MINUTE` | 签到时间（分钟） | `0` |
| `RETRY_TIMES` | 重试次数 | `3` |

## 常用命令

```bash
# 启动（前台，可看日志）
docker-compose up

# 启动（后台）
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down

# 重新构建
docker-compose up --build -d
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

1. **首次登录必须交互式运行**（不能用 `-d`），需要输入验证码
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
- 确认已加入终点站群组并关注机器人

### Session 失效
- 删除 `./sessions` 目录
- 重新配置 `PHONE_NUMBER`
- 重新登录
