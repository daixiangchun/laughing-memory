# 部署说明

本项目是一个 FastAPI 服务，同时托管问答页和管理页，所以只需要部署一个容器。
PostgreSQL 是可选的：只用来存查询日志，数据库不可用时问答照常工作。

## 0. 部署前准备

- 大模型密钥：在部署平台的环境变量里填 `OPENAI_API_KEY`，**不要写进代码或镜像**。
- 向量索引：`backend/data/index/` 随代码一起提交（约 17MB），部署时不需要重新抓文档。
- 内存：嵌入模型和 torch 都要常驻内存。**建议至少 1GB**，512MB 的免费档大概率会 OOM（未实测，按依赖体积估计）。

## 1. 需要提交到 Git 的文件

| 提交 | 不提交 |
| --- | --- |
| `Dockerfile`、`.dockerignore`、`compose.yaml` | `.env`（含密钥与数据库密码） |
| `requirements.in`、`requirements.txt` | `.venv/`、`.cache/`、`__pycache__/` |
| `backend/`（代码、`static/`、`data/index/`、`data/eval/`） | `backend/data/raw/`（约 67MB，可重新抓取） |
| `tests/`、`docs/`、`README.md` | `backend/data/processed/`、`backend/data/cache/`、`ARCHITECTURE.md` |
| `.github/workflows/ci.yml`、`.gitignore`、`.env.example` | `.pytest_cache/`、`.vscode/` |

提交前建议检查一次：

```powershell
git status --short
git check-ignore -v .env backend/data/raw
```

如果 `backend/data/raw` 之前已经被 git 跟踪过，需要先取消跟踪：`git rm -r --cached backend/data/raw`。

## 2. 方案 A：平台托管（推荐，适合给面试官一个链接）

以 Render 为例（Railway、Fly.io 步骤类似）：

1. 把仓库推到 GitHub。
2. 在 Render 新建 **Web Service**，选择该仓库，运行环境选 **Docker**（会自动读取根目录的 `Dockerfile`）。
3. 实例规格选至少 1GB 内存。
4. 在 **Environment** 里添加变量：

   | 变量 | 值 |
   | --- | --- |
   | `OPENAI_API_KEY` | 你的 DeepSeek 密钥 |
   | `OPENAI_API_BASE` | `https://api.deepseek.com` |
   | `OPENAI_MODEL` | `deepseek-chat`（已在本机验证可用） |
   | `TRUST_PROXY_HEADERS` | `true`（平台网关在前面，限流才能按真实 IP 计数） |
   | `DATABASE_URL` | 可选。用托管 PostgreSQL（如 Neon、Supabase）的连接串；不填则查询日志功能关闭 |

5. 健康检查路径填 `/api/health`。平台会注入 `PORT`，镜像启动命令已经读取它。
6. 部署完成后访问平台给出的域名：问答页在 `/`，管理页在 `/admin.html`。

**注意**：Render 等平台的免费实例会在空闲后休眠，第一次访问需要等待几十秒冷启动。面试前提前打开一次。

## 3. 方案 B：自有服务器（VPS）+ Docker Compose

适合已经有一台 Linux 服务器的情况。

```bash
# 服务器上
git clone <你的仓库地址> && cd <项目目录>
cp .env.example .env        # 然后编辑 .env：填写 OPENAI_API_KEY、POSTGRES_* 等
docker compose up -d db                       # 先启动数据库
docker compose --profile app up -d --build    # 构建并启动应用（只绑定 127.0.0.1:8000）
docker compose exec app python backend/scripts/init_db.py   # 可选：建查询日志表
```

对外访问需要一层 HTTPS 反向代理。最省事的是 Caddy，自动申请证书，`Caddyfile` 只需一行：

```
your-domain.com {
    reverse_proxy 127.0.0.1:8000
}
```

代理之后记得在 `.env` 里设置 `TRUST_PROXY_HEADERS=true`，然后 `docker compose --profile app up -d` 重启应用。

## 4. 本地验证镜像（推荐提交前做一次）

需要 Docker Desktop。

```powershell
docker build -t py-doc-qa .
docker run --rm -p 8000:8000 -e OPENAI_API_KEY=你的密钥 -e OPENAI_MODEL=deepseek-chat py-doc-qa
# 浏览器打开 http://127.0.0.1:8000/
```

国内网络构建时，下载嵌入模型可能超时，可以指定镜像站：

```powershell
docker build --build-arg HF_ENDPOINT=https://hf-mirror.com -t py-doc-qa .
```

## 5. 环境变量速查

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 空 | 为空时问答退化为「文档原文摘录」，并在页面标注 |
| `OPENAI_API_BASE` | `https://api.deepseek.com` | 任何 OpenAI 兼容接口 |
| `OPENAI_MODEL` | 见 `config.py` | 建议显式设置 |
| `DATABASE_URL` | 本机 127.0.0.1 | 容器里不可达时，数据库相关接口返回 503，问答不受影响 |
| `RATE_LIMIT_PER_MINUTE` | `20` | 每个 IP 每分钟最多提问次数，`0` 关闭 |
| `TRUST_PROXY_HEADERS` | `false` | 仅在可信反向代理之后设为 `true` |
| `PORT` | `8000` | 由平台注入 |

## 6. 已知限制

- 限流是进程内计数：只能单实例运行（镜像已固定 `--workers 1`）。多实例需要换成 Redis 之类的共享计数。
- 索引在镜像构建时打包，更新语料后需要重新构建镜像。
- 嵌入模型在构建时下载并写入镜像，运行时不联网。
- 会话保存在浏览器 localStorage，服务端没有用户体系，公开链接任何人都可以提问（受限流约束）。
