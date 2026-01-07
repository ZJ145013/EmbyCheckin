FROM python:3.11-slim

WORKDIR /app

# Install sing-box for advanced proxy protocols (ss/vless/hysteria2)
ARG SINGBOX_VERSION=1.10.7
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/sing-box-${SINGBOX_VERSION}-linux-amd64.tar.gz" \
       | tar -xzf - -C /tmp \
    && mv /tmp/sing-box-${SINGBOX_VERSION}-linux-amd64/sing-box /usr/local/bin/ \
    && chmod +x /usr/local/bin/sing-box \
    && rm -rf /tmp/sing-box-* \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY embycheckin/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY embycheckin ./embycheckin
COPY tools ./tools

# Create directories
RUN mkdir -p /app/data /app/sessions /app/logs

# Set timezone
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

EXPOSE 8765

CMD ["python", "-m", "uvicorn", "embycheckin.app:app", "--host", "0.0.0.0", "--port", "8765"]
