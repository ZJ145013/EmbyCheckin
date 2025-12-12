#!/usr/bin/env python3
"""
终点站 (Terminus) Telegram 自动签到脚本
使用 Gemini Vision API 识别验证码
"""

import asyncio
import base64
import json
import os
import random
import re
import sys
from datetime import datetime, time, timedelta
from io import BytesIO
from typing import Optional, Tuple

import httpx
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError

# ==================== 配置 ====================

# Telegram 配置
API_ID = int(os.getenv("API_ID", "2040"))
API_HASH = os.getenv("API_HASH", "b18441a1ff607e10a989891a5462e627")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")  # 首次登录需要

# Gemini 配置
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://geminicli.942645.xyz")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "sk-zjzj5522")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# 签到配置
BOT_USERNAME = "EmbyPublicBot"
CHECKIN_HOUR = int(os.getenv("CHECKIN_HOUR", "9"))  # 每天签到时间（小时）
CHECKIN_MINUTE = int(os.getenv("CHECKIN_MINUTE", "0"))  # 每天签到时间（分钟）
RETRY_TIMES = int(os.getenv("RETRY_TIMES", "3"))  # 重试次数
SESSION_NAME = os.getenv("SESSION_NAME", "terminus_checkin")

# ==================== 日志配置 ====================

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    level="INFO",
)
logger.add(
    "logs/checkin_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    level="DEBUG",
    rotation="1 day",
    retention="7 days",
)


# ==================== Gemini Vision API ====================

async def analyze_image_with_gemini(
    image_data: bytes,
    options: list[str]
) -> Tuple[Optional[str], Optional[str]]:
    """
    使用 Gemini Vision API 分析验证码图片

    Args:
        image_data: 图片二进制数据
        options: 可选的答案列表

    Returns:
        (答案, 错误信息)
    """
    try:
        # 将图片转为 base64
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        # 构建 prompt
        options_text = "、".join([f"「{opt}」" for opt in options])
        prompt = f"""这是一个验证码图片，请仔细观察图片内容。

可选答案有：{options_text}

请根据图片内容，从上述选项中选择最匹配的一个答案。
只需要回复选项内容本身，不要有任何其他文字、标点或解释。

例如，如果答案是「猫」，就只回复：猫"""

        # 构建请求
        url = f"{GEMINI_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {GEMINI_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": GEMINI_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ],
            "max_tokens": 100,
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()

            result = response.json()
            answer = result["choices"][0]["message"]["content"].strip()

            # 清理答案（去除可能的引号、空格等）
            answer = answer.strip("「」\"'""''")
            answer = re.sub(r'^[选择]?[项]?[:：]?\s*', '', answer)

            logger.debug(f"Gemini 原始回答: {answer}")

            return answer, None

    except httpx.HTTPStatusError as e:
        error_msg = f"Gemini API HTTP 错误: {e.response.status_code}"
        logger.error(error_msg)
        return None, error_msg
    except Exception as e:
        error_msg = f"Gemini API 调用失败: {str(e)}"
        logger.error(error_msg)
        return None, error_msg


def find_best_match(answer: str, options: list[str]) -> Optional[str]:
    """
    从选项中找到最匹配的答案
    """
    if not answer or not options:
        return None

    answer_clean = answer.lower().strip()

    # 精确匹配
    for opt in options:
        if opt.lower().strip() == answer_clean:
            return opt

    # 包含匹配
    for opt in options:
        if answer_clean in opt.lower() or opt.lower() in answer_clean:
            return opt

    # 模糊匹配（去除 emoji 和空格后比较）
    def clean_text(text: str) -> str:
        # 移除 emoji 和特殊字符
        import unicodedata
        cleaned = ''.join(
            c for c in text
            if unicodedata.category(c) not in ('So', 'Mn', 'Mc', 'Me')
        )
        return cleaned.replace(" ", "").lower()

    answer_cleaned = clean_text(answer)
    for opt in options:
        if clean_text(opt) == answer_cleaned:
            return opt
        if answer_cleaned in clean_text(opt) or clean_text(opt) in answer_cleaned:
            return opt

    logger.warning(f"无法匹配答案 '{answer}' 到选项 {options}")
    return None


# ==================== 签到逻辑 ====================

class TerminusCheckin:
    def __init__(self, client: Client):
        self.client = client
        self.finished = asyncio.Event()
        self.success = False
        self.already_checked = False  # 今日已签到标记
        self.message_to_click: Optional[Message] = None

    async def start(self) -> bool:
        """执行签到流程"""
        self.finished.clear()
        self.success = False
        self.already_checked = False
        self.message_to_click = None

        logger.info("开始终点站签到...")

        # 只尝试一次，不重复发送命令
        try:
            # 随机延迟 2-5 秒，模拟人工操作
            delay = random.uniform(2, 5)
            logger.debug(f"等待 {delay:.1f} 秒...")
            await asyncio.sleep(delay)

            # 直接发送签到命令（不发 /cancel，减少请求）
            await self.client.send_message(BOT_USERNAME, "/checkin")
            logger.info("已发送签到命令，等待机器人响应...")

            # 等待签到完成（超时60秒）
            try:
                await asyncio.wait_for(self.finished.wait(), timeout=60)
            except asyncio.TimeoutError:
                logger.warning("签到超时")
                return False

            if self.success or self.already_checked:
                if self.already_checked:
                    logger.info("今日已签到，无需重复")
                else:
                    logger.info("签到成功！")
                return True
            else:
                # 签到失败，只在验证码错误时重试
                logger.warning("签到失败")
                return False

        except FloodWait as e:
            logger.warning(f"触发 Telegram 限制，等待 {e.value} 秒")
            await asyncio.sleep(e.value)
            return False
        except Exception as e:
            logger.error(f"签到出错: {e}")
            return False

    async def handle_message(self, client: Client, message: Message):
        """处理机器人消息"""
        try:
            text = message.text or message.caption or ""

            # 记录所有收到的消息
            logger.info(f"收到机器人消息: {text[:200] if text else '[图片/媒体]'}")

            # 忽略的消息
            if any(kw in text for kw in ["会话已取消", "没有活跃的会话"]):
                logger.debug(f"忽略消息: {text[:50]}")
                return

            # 处理验证码图片（优先处理）
            if message.photo and message.reply_markup:
                await self.handle_captcha(message)
                return

            # 仅有图片没有按钮
            if message.photo:
                logger.info("收到图片但没有按钮，等待后续消息...")
                return

            # 已签到的各种表述
            already_checked_keywords = [
                "今天已签到", "已经签到", "今日已签到", "已签到",
                "重复签到", "已经签过", "签过到了", "已完成签到",
                "签到机会已用完", "已用完"
            ]
            if any(kw in text for kw in already_checked_keywords):
                # 尝试提取总分
                match = re.search(r"总分[：:]\s*(\d+)", text)
                if match:
                    logger.info(f"今日已签到，当前总分: {match.group(1)}")
                else:
                    logger.info(f"今日已签到: {text[:100]}")
                self.already_checked = True
                self.finished.set()
                return

            # 签到成功的各种表述
            success_keywords = [
                "签到成功", "成功签到", "获得", "+", "积分",
                "恭喜", "完成签到", "签到完成"
            ]
            if any(kw in text for kw in success_keywords):
                # 尝试提取积分信息
                match = re.search(r"[+＋]?\s*(\d+)\s*[积分点]", text)
                if match:
                    logger.info(f"签到成功！获得 {match.group(1)} 积分")
                else:
                    # 尝试其他格式
                    match2 = re.search(r"(\d+)", text)
                    if match2:
                        logger.info(f"签到成功！积分相关: {match2.group(1)}")
                    else:
                        logger.info(f"签到成功！{text[:100]}")
                self.success = True
                self.finished.set()
                return

            # 签到失败/错误的各种表述
            fail_keywords = [
                "失败", "错误", "验证码错误", "回答错误",
                "答案错误", "超时", "过期", "无效"
            ]
            if any(kw in text for kw in fail_keywords):
                logger.warning(f"签到失败: {text[:100]}")
                self.success = False
                self.finished.set()
                return

            # 账号问题
            account_fail_keywords = [
                "黑名单", "封禁", "禁止", "未注册", "不存在",
                "未绑定", "请先绑定", "请先注册"
            ]
            if any(kw in text for kw in account_fail_keywords):
                logger.error(f"账号问题: {text[:100]}")
                self.success = False
                self.finished.set()
                return

            # 其他未识别的消息，记录但不结束
            logger.warning(f"未识别的消息类型: {text[:200]}")

        except Exception as e:
            logger.error(f"处理消息出错: {e}")

    async def handle_captcha(self, message: Message):
        """处理验证码"""
        try:
            logger.info("收到验证码图片，正在识别...")

            # 获取按钮选项
            if not message.reply_markup or not message.reply_markup.inline_keyboard:
                logger.error("没有找到选项按钮")
                return

            options = []
            for row in message.reply_markup.inline_keyboard:
                for button in row:
                    if button.text:
                        options.append(button.text)

            if not options:
                logger.error("选项为空")
                return

            # 清理选项文本（用于 API 识别）
            def clean_option(text: str) -> str:
                # 移除 emoji
                import unicodedata
                cleaned = ''.join(
                    c for c in text
                    if unicodedata.category(c) not in ('So', 'Mn', 'Mc', 'Me')
                )
                return cleaned.replace(" ", "").strip()

            options_cleaned = [clean_option(opt) for opt in options]
            options_cleaned = [opt for opt in options_cleaned if opt]  # 移除空字符串

            logger.info(f"选项: {options}")
            logger.debug(f"清理后选项: {options_cleaned}")

            # 下载图片
            photo_data = await self.client.download_media(message, in_memory=True)
            if isinstance(photo_data, BytesIO):
                image_bytes = photo_data.getvalue()
            else:
                image_bytes = photo_data

            # 调用 Gemini 识别
            answer, error = await analyze_image_with_gemini(image_bytes, options_cleaned)

            if error:
                logger.error(f"验证码识别失败: {error}")
                self.finished.set()
                return

            logger.info(f"Gemini 识别结果: {answer}")

            # 匹配答案到原始选项
            matched_option = find_best_match(answer, options)

            if not matched_option:
                # 尝试用清理后的选项匹配
                matched_clean = find_best_match(answer, options_cleaned)
                if matched_clean:
                    idx = options_cleaned.index(matched_clean)
                    matched_option = options[idx]

            if not matched_option:
                logger.error(f"无法匹配答案 '{answer}' 到选项")
                self.finished.set()
                return

            logger.info(f"点击选项: {matched_option}")

            # 随机延迟，模拟人工操作
            await asyncio.sleep(random.uniform(1, 3))

            # 点击按钮
            try:
                await message.click(matched_option)
            except RPCError as e:
                logger.error(f"点击按钮失败: {e}")
                self.finished.set()

        except Exception as e:
            logger.error(f"处理验证码出错: {e}")
            self.finished.set()


# ==================== 定时任务 ====================

async def wait_until_next_checkin() -> None:
    """等待到下一次签到时间"""
    now = datetime.now()
    target_time = now.replace(
        hour=CHECKIN_HOUR,
        minute=CHECKIN_MINUTE,
        second=0,
        microsecond=0
    )

    # 如果今天的签到时间已过，等到明天
    if now >= target_time:
        target_time += timedelta(days=1)

    wait_seconds = (target_time - now).total_seconds()

    # 添加随机延迟（0-30分钟），避免被检测
    random_delay = random.randint(0, 1800)
    wait_seconds += random_delay

    logger.info(
        f"下次签到时间: {target_time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"(随机延迟 {random_delay // 60} 分钟)"
    )
    logger.info(f"等待 {wait_seconds / 3600:.2f} 小时...")

    await asyncio.sleep(wait_seconds)


async def run_scheduled_checkin(client: Client, checkin: TerminusCheckin):
    """运行定时签到任务"""
    while True:
        try:
            # 执行签到
            await checkin.start()

            # 等待下一次签到
            await wait_until_next_checkin()

        except asyncio.CancelledError:
            logger.info("定时任务已取消")
            break
        except Exception as e:
            logger.error(f"定时任务出错: {e}")
            # 出错后等待1小时再重试
            await asyncio.sleep(3600)


# ==================== 主程序 ====================

async def main():
    """主函数"""
    logger.info("=" * 50)
    logger.info("终点站 (Terminus) 自动签到")
    logger.info("=" * 50)

    # 确保日志目录存在
    os.makedirs("logs", exist_ok=True)
    os.makedirs("sessions", exist_ok=True)

    # 创建客户端
    client = Client(
        name=f"sessions/{SESSION_NAME}",
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=PHONE_NUMBER if PHONE_NUMBER else None,
    )

    checkin = TerminusCheckin(client)

    async with client:
        logger.info(f"已登录: {client.me.first_name} (@{client.me.username})")

        # 获取机器人信息
        try:
            bot = await client.get_users(BOT_USERNAME)
            logger.info(f"目标机器人: {bot.first_name} (@{bot.username}, ID: {bot.id})")
        except Exception as e:
            logger.error(f"获取机器人信息失败: {e}")
            return

        # 注册消息处理器 - 使用机器人 ID 确保匹配
        @client.on_message(filters.user(bot.id) & filters.private)
        async def message_handler(client: Client, message: Message):
            await checkin.handle_message(client, message)

        # 检查是否需要立即签到
        run_now = os.getenv("RUN_NOW", "false").lower() == "true"
        if run_now:
            logger.info("立即执行签到...")
            await checkin.start()
        else:
            logger.info("跳过立即签到，等待定时任务...")

        # 启动定时任务
        logger.info(f"启动定时签到任务，每天 {CHECKIN_HOUR:02d}:{CHECKIN_MINUTE:02d} 执行")
        await run_scheduled_checkin(client, checkin)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序已退出")
