# 使用一个轻量级的 Python 基础镜像
FROM python:3.11-slim

# [✅ SSL 修复] 安装系统级的 CA 证书包
# 这可以解决 Python 无法验证 SSL 证书的问题
RUN apt-get update && \
    apt-get install -y ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装依赖
# --no-cache-dir 不保留缓存，--default-timeout 增加超时防止网络问题
RUN pip install --no-cache-dir --default-timeout=100 -r requirements.txt

# 创建一个用于存放源码的目录
RUN mkdir -p /app/src
WORKDIR /app/src

# 复制源码
# (我们将在 docker-compose.yml 中使用 volume 挂载 src，
#  但这里也 COPY 一份，确保镜像可以独立构建)
COPY src/ .

# 容器启动时运行的主命令
CMD ["python", "mail_processor.py"]