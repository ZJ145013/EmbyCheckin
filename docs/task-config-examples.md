# EmbyCheckin 任务配置示例

本文档提供各种常见任务的配置模板，可直接复制使用。

---

## 任务类型说明

| 类型 | 说明 | 适用场景 |
|------|------|----------|
| `bot_checkin` | 通用机器人签到 | 需要发送命令并等待响应的签到任务 |
| `send_message` | 简单消息发送 | 仅发送消息，不等待响应的保活任务 |

---

## 一、Terminus (终点站) 签到

**特点：** 需要 AI 识别图片验证码

```json
{
  "name": "Terminus 每日签到",
  "type": "bot_checkin",
  "target": "EmbyPublicBot",
  "schedule_cron": "0 9 * * *",
  "timezone": "Asia/Shanghai",
  "params": {
    "command": "/checkin",
    "timeout": 60,
    "use_ai": true,
    "captcha_has_image": true,
    "captcha_has_buttons": true,
    "random_delay_min": 2.0,
    "random_delay_max": 5.0,
    "success_patterns": {
      "keywords": ["签到成功", "成功签到", "获得", "积分", "恭喜", "完成签到"],
      "extract_regex": "[+＋]?\\s*(\\d+)\\s*[积分点]"
    },
    "already_checked_patterns": {
      "keywords": ["今天已签到", "已经签到", "今日已签到", "已签到", "重复签到", "签到机会已用完"]
    },
    "fail_patterns": {
      "keywords": ["失败", "错误", "验证码错误", "回答错误", "超时", "过期", "无效"]
    },
    "ignore_patterns": {
      "keywords": ["会话已取消", "没有活跃的会话"]
    },
    "account_error_patterns": {
      "keywords": ["黑名单", "封禁", "禁止", "未注册", "不存在", "未绑定"]
    }
  }
}
```

---

## 二、普通签到机器人 (无验证码)

**特点：** 发送命令后直接返回结果，无需 AI

```json
{
  "name": "XXX 签到",
  "type": "bot_checkin",
  "target": "YourBotUsername",
  "schedule_cron": "30 8 * * *",
  "timezone": "Asia/Shanghai",
  "params": {
    "command": "/checkin",
    "timeout": 30,
    "use_ai": false,
    "random_delay_min": 1.0,
    "random_delay_max": 3.0,
    "success_patterns": {
      "keywords": ["签到成功", "打卡成功", "check in", "success"],
      "extract_regex": "(\\d+)\\s*(?:积分|分|points)"
    },
    "already_checked_patterns": {
      "keywords": ["已签到", "already", "重复"]
    },
    "fail_patterns": {
      "keywords": ["失败", "fail", "error"]
    },
    "ignore_patterns": {
      "keywords": []
    },
    "account_error_patterns": {
      "keywords": ["未注册", "not found"]
    }
  }
}
```

---

## 三、Emby/Jellyfin 服务保活

**特点：** 定期发送消息保持账号活跃

```json
{
  "name": "Emby 保活",
  "type": "bot_checkin",
  "target": "EmbyBot",
  "schedule_cron": "0 */6 * * *",
  "timezone": "Asia/Shanghai",
  "params": {
    "command": "/start",
    "timeout": 30,
    "use_ai": false,
    "random_delay_min": 1.0,
    "random_delay_max": 5.0,
    "success_patterns": {
      "keywords": ["欢迎", "welcome", "你好", "hello", "菜单", "menu"]
    },
    "already_checked_patterns": {
      "keywords": []
    },
    "fail_patterns": {
      "keywords": ["error", "失败", "blocked"]
    },
    "ignore_patterns": {
      "keywords": []
    },
    "account_error_patterns": {
      "keywords": ["banned", "封禁", "过期", "expired"]
    }
  }
}
```

---

## 四、简单消息保活

**特点：** 仅发送消息，不处理响应

```json
{
  "name": "Bot 保活消息",
  "type": "send_message",
  "target": "SomeBotUsername",
  "schedule_cron": "0 12 * * *",
  "timezone": "Asia/Shanghai",
  "params": {
    "message": "/start"
  }
}
```

---

## 五、PT 站签到

**特点：** PT 站机器人签到，通常有积分奖励

```json
{
  "name": "PT站签到",
  "type": "bot_checkin",
  "target": "PTSiteBot",
  "schedule_cron": "0 10 * * *",
  "timezone": "Asia/Shanghai",
  "params": {
    "command": "/sign",
    "timeout": 45,
    "use_ai": false,
    "random_delay_min": 2.0,
    "random_delay_max": 8.0,
    "success_patterns": {
      "keywords": ["签到成功", "获得", "魔力", "bonus", "积分"],
      "extract_regex": "(?:获得|得到|\\+)\\s*(\\d+(?:\\.\\d+)?)\\s*(?:魔力|积分|bonus)"
    },
    "already_checked_patterns": {
      "keywords": ["已签到", "已经签过", "今日已签"]
    },
    "fail_patterns": {
      "keywords": ["签到失败", "error", "失败"]
    },
    "ignore_patterns": {
      "keywords": []
    },
    "account_error_patterns": {
      "keywords": ["账号异常", "被禁", "banned", "未绑定"]
    }
  }
}
```

---

## 六、带文字验证码的签到

**特点：** 需要 AI 识别文字验证码（非图片按钮）

```json
{
  "name": "文字验证码签到",
  "type": "bot_checkin",
  "target": "TextCaptchaBot",
  "schedule_cron": "0 9 * * *",
  "timezone": "Asia/Shanghai",
  "params": {
    "command": "/checkin",
    "timeout": 60,
    "use_ai": true,
    "captcha_has_image": true,
    "captcha_has_buttons": true,
    "random_delay_min": 2.0,
    "random_delay_max": 5.0,
    "success_patterns": {
      "keywords": ["成功", "完成", "通过"],
      "extract_regex": null
    },
    "already_checked_patterns": {
      "keywords": ["已完成", "已签到"]
    },
    "fail_patterns": {
      "keywords": ["错误", "失败", "wrong", "incorrect"]
    },
    "ignore_patterns": {
      "keywords": ["请选择", "请点击"]
    },
    "account_error_patterns": {
      "keywords": ["无权限", "未授权"]
    }
  }
}
```

---

## Cron 表达式参考

| 表达式 | 说明 |
|--------|------|
| `0 9 * * *` | 每天 9:00 |
| `30 8 * * *` | 每天 8:30 |
| `0 */6 * * *` | 每 6 小时 |
| `0 9,21 * * *` | 每天 9:00 和 21:00 |
| `0 9 * * 1-5` | 工作日 9:00 |
| `0 0 1 * *` | 每月 1 号 0:00 |
| `*/30 * * * *` | 每 30 分钟 |

**格式：** `分 时 日 月 周`

---

## 配置字段说明

### 基础字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 任务名称，用于显示和日志 |
| `type` | string | 是 | 任务类型：`bot_checkin` 或 `send_message` |
| `target` | string | 是 | 目标机器人用户名（不含 @） |
| `schedule_cron` | string | 是 | Cron 表达式 |
| `timezone` | string | 否 | 时区，默认 `Asia/Shanghai` |
| `retries` | int | 否 | 失败重试次数，默认 0 |
| `max_runtime_seconds` | int | 否 | 任务超时时间，默认 120 |
| `jitter_seconds` | int | 否 | 随机延迟秒数，默认 0 |

### bot_checkin 参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command` | string | 是 | 发送的签到命令 |
| `timeout` | int | 否 | 等待响应超时，默认 60 秒 |
| `use_ai` | bool | 否 | 是否使用 AI 识别验证码 |
| `captcha_has_image` | bool | 否 | 验证码是否包含图片 |
| `captcha_has_buttons` | bool | 否 | 验证码是否有按钮选项 |
| `random_delay_min` | float | 否 | 发送前最小延迟，默认 2.0 |
| `random_delay_max` | float | 否 | 发送前最大延迟，默认 5.0 |
| `success_patterns` | object | 否 | 成功消息匹配模式 |
| `already_checked_patterns` | object | 否 | 已签到消息匹配模式 |
| `fail_patterns` | object | 否 | 失败消息匹配模式 |
| `ignore_patterns` | object | 否 | 忽略的消息模式 |
| `account_error_patterns` | object | 否 | 账号错误消息模式 |

### 消息匹配模式 (MessagePattern)

| 字段 | 类型 | 说明 |
|------|------|------|
| `keywords` | array | 关键词列表，任一匹配即触发 |
| `regex` | string | 正则表达式匹配（可选） |
| `extract_regex` | string | 用于提取数据的正则，如提取积分数字 |

### send_message 参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | 是 | 要发送的消息内容 |

---

## 常见问题

### Q: 如何确定机器人的用户名？
A: 在 Telegram 中打开机器人，查看其 `@username`，去掉 `@` 即可。

### Q: 签到失败怎么排查？
A: 查看执行日志，检查：
1. 关键词是否匹配机器人的实际响应
2. 超时时间是否足够
3. 如需 AI，检查 AI 配置是否正确

### Q: 如何添加新的关键词？
A: 在对应的 `patterns.keywords` 数组中添加新关键词即可。

### Q: extract_regex 怎么写？
A: 使用 Python 正则语法，用括号 `()` 捕获要提取的内容。例如：
- `(\d+)` - 提取数字
- `获得\s*(\d+)\s*积分` - 提取 "获得 100 积分" 中的 100
