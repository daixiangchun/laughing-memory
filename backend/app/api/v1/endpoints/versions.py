"""版本与索引状态接口"""
from fastapi import APIRouter

from backend.app.config import LIBRARIES
from backend.app.retrieval.hybrid import ensure_indexes_loaded
from backend.app.retrieval.vector_store import vector_index

router = APIRouter()


@router.get("/versions", summary="已支持的库与版本")
def versions():
    ensure_indexes_loaded()
    index_by_version = {}
    for chunk in vector_index.chunks.values():
        key = f"{chunk['library']}@{chunk['version']}"
        index_by_version[key] = index_by_version.get(key, 0) + 1
    return {
        "libraries": [
            {
                "library": lib,
                "versions": [
                    {
                        "version": version,
                        "indexed_chunks": index_by_version.get(f"{lib}@{version}", 0),
                    }
                    for version in versions_map
                ],
            }
            for lib, versions_map in LIBRARIES.items()
        ]
    }


@router.get("/index/status", summary="索引状态")
def index_status():
    ensure_indexes_loaded()
    return vector_index.stats()
