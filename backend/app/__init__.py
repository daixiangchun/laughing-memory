"""版本感知文档问答后端。

包被导入时做两件事，且必须赶在 huggingface_hub / sentence-transformers 之前：

1. 加载 .env —— huggingface_hub 在**导入时**就固化 HF_ENDPOINT，之后设置无效。
2. 本地已有嵌入模型缓存时开启离线模式 —— 否则每次进程启动都会去镜像站
   做 HEAD 检查，网络慢时单次问答被拖到 60 秒以上（纯等待，不产生任何收益）。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _enable_hf_offline_if_cached() -> None:
    """模型已缓存则跳过联网检查（不改变下载行为，只避免无谓的重试等待）"""
    if os.environ.get("HF_HUB_OFFLINE"):
        return

    model = os.environ.get("EMBEDDING_MODEL", _DEFAULT_MODEL)
    cache_root = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    repo_dir = cache_root / ("models--" + model.replace("/", "--"))
    # snapshot 目录非空才算真正可用（只有空壳目录时仍然联网下载）
    if repo_dir.is_dir() and any((repo_dir / "snapshots").glob("*/*")):
        os.environ["HF_HUB_OFFLINE"] = "1"


_enable_hf_offline_if_cached()
