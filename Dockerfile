FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装调度器额外依赖
COPY embycheckin/requirements.txt ./embycheckin-requirements.txt
RUN pip install --no-cache-dir -r embycheckin-requirements.txt

# 复制代码
COPY checkin.py .
COPY docker_entrypoint.py .
COPY tools ./tools
COPY embycheckin ./embycheckin

# 创建目录
RUN mkdir -p /app/sessions /app/logs /app/data

# 设置时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 默认运行旧版签到入口（兼容）
# 新版调度器使用: python -m uvicorn embycheckin.app:app --host 0.0.0.0 --port 8000
CMD ["python", "-u", "docker_entrypoint.py"]
