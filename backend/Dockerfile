# syntax=docker/dockerfile:1
# backend/Dockerfile — 多阶段构建: builder(带编译工具链) → runtime(干净 slim)

# ---------- Stage 1: builder — 编译工具链 + 依赖装入独立 venv ----------
FROM python:3.12-slim AS builder

# aiomysql 纯 Python 免编译；保留 build-essential/g++ 是给 hmmlearn、scikit-learn
# 等在无预编译 wheel 场景下兜底
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        g++ \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 依赖装进独立 venv，runtime 阶段整体 COPY，不带任何构建工具
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 先只 COPY 依赖清单 → 装依赖：源码改动不再触发依赖层重建（层缓存）
# uv.lock 已 stale（缺 auth 依赖），构建走 pip 路线，不 COPY uv.lock
COPY pyproject.toml ./

# 不用 `pip install .`：backend/ 顶层有 alembic/、scripts/（均含 __init__.py），
# setuptools flat-layout 自动发现会报 "Multiple top-level packages" 导致构建失败。
# 这里用标准库 tomllib 从 pyproject 提取依赖清单安装（纯 pip，语义与 pip install . 的
# 依赖解析一致）；app 源码在 runtime 阶段 COPY 进镜像，镜像仍为不可变制品（无 bind mount）
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import tomllib;open('/tmp/deps.txt','w').write('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" \
    && pip install --no-cache-dir -r /tmp/deps.txt

# ---------- Stage 2: runtime — 干净 slim + venv + 源码 ----------
FROM python:3.12-slim AS runtime

# tzdata：保障 TZ=Asia/Shanghai 与 zoneinfo 数据在 slim 镜像可用
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"
# uvicorn console script 不会把 cwd 加进 sys.path，显式暴露 /app 下的 app 包
ENV PYTHONPATH=/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app ./app

# 非 root 运行
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# 仅声明，不映射到宿主机（对外只暴露 frontend 的 80）
EXPOSE 8000

# exec 形式：SIGTERM 直达 uvicorn → lifespan shutdown → stop_scheduler
# --workers 1 硬要求：调度器跑在 lifespan 进程内，多 worker = 重复调度
# --proxy-headers + 内网网段：信任 frontend(nginx) 容器的 X-Forwarded-* 头
# 不加 --root-path：nginx 的 proxy_pass 保留 /api 前缀，后端无需感知外层路径
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "172.16.0.0/12,10.0.0.0/8,192.168.0.0/16,127.0.0.1"]
