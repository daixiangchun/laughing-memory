# 生产镜像：FastAPI 后端 + 原生前端（由后端静态托管）+ 已构建好的 FAISS 索引
# 构建：docker build -t py-doc-qa .
# 运行：docker run -p 8000:8000 -e OPENAI_API_KEY=sk-xxx py-doc-qa

FROM python:3.14-slim

# 构建参数：国内网络构建时可传 --build-arg HF_ENDPOINT=https://hf-mirror.com
ARG TORCH_VERSION=2.15.0
ARG HF_ENDPOINT=https://huggingface.co

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    HF_HOME=/app/.hf-cache

WORKDIR /app

# 1) CPU 版 torch（--no-deps 避免把 PyPI 上 Linux 版附带的数 GB CUDA 依赖装进来）
#    其余依赖由 requirements.txt 统一锁定，其中 torch==2.15.0 已由这里满足
RUN pip install --no-deps --index-url https://download.pytorch.org/whl/cpu "torch==${TORCH_VERSION}"

# 2) 锁定的应用依赖（先复制 requirements.txt，代码改动时不必重装依赖）
COPY requirements.txt .
RUN pip install -r requirements.txt

# 3) 构建期下载嵌入模型，运行时离线加载（容器启动不访问外网）
RUN HF_ENDPOINT=${HF_ENDPOINT} python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# 4) 应用代码、索引与评测数据（.dockerignore 已排除原始语料、.env 与密钥）
COPY backend ./backend

# 非 root 运行；上传/缓存目录需要可写
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/backend/data/documents /app/backend/data/cache \
    && chown -R app:app /app
USER app

# 运行时只读本地缓存，不再联网检查模型
ENV HF_HUB_OFFLINE=1 \
    DEBUG=false

EXPOSE 8000

# 平台（Render / Railway / Fly 等）通常会注入 PORT；本地默认 8000
# 单 worker：每个进程都会加载一份嵌入模型，多 worker 会成倍占用内存
CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
