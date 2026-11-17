"""评测结果接口"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.app.config import get_settings

router = APIRouter()


@router.get("/eval/results", summary="读取最近一次评测结果")
def eval_results():
    path = Path(get_settings().EVAL_DIR) / "results.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="尚未运行评测，请先执行 backend/scripts/run_eval.py")
    return json.loads(path.read_text(encoding="utf-8"))
