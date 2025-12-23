from .base import (
    TaskHandler,
    TaskContext,
    TaskResult,
    TaskSnapshot,
    AccountSnapshot,
    register_task_handler,
    get_task_handler,
    list_task_types,
    validate_task_params,
)

# 任务类型说明：
# - SendMessageTask (send_message): 简单消息发送，用于保活或触发机器人
# - BotCheckinTask (bot_checkin): 命令式签到，发送 /checkin 等命令，支持 AI 验证码识别
# - ButtonCheckinTask (button_checkin): 面板按钮签到，先发命令显示面板，再点击指定按钮

from .send_message import SendMessageTask
from .bot_checkin import BotCheckinTask
from .button_checkin import ButtonCheckinTask

__all__ = [
    "TaskHandler",
    "TaskContext",
    "TaskResult",
    "TaskSnapshot",
    "AccountSnapshot",
    "register_task_handler",
    "get_task_handler",
    "list_task_types",
    "validate_task_params",
    "SendMessageTask",
    "BotCheckinTask",
    "ButtonCheckinTask",
]
