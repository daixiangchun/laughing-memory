-- 查询日志：每一次 /api/v1/query 的结果都落库
-- 用途：运营视角的「用户问了什么、判成了什么、慢在哪」，以及语料缺口分析
-- （某类问题频繁被拒答 = 该补哪部分文档）

CREATE TABLE IF NOT EXISTS query_logs (
    id              BIGSERIAL PRIMARY KEY,
    question        TEXT        NOT NULL,
    library         TEXT,                      -- 请求里限定的库，可为空
    request_version TEXT,                      -- 请求里限定的版本，可为空
    mode            TEXT        NOT NULL,      -- pre / post / none
    status          TEXT        NOT NULL,      -- answer / conflict / refused
    resolved_versions TEXT[],                  -- 实际参与检索的版本
    top_score       REAL,                      -- 最佳向量相似度
    retrieved       INT,                       -- 参与生成的片段数
    elapsed_ms      INT,
    used_llm        BOOLEAN,                   -- false 表示走了文档摘录兜底
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_query_logs_created_at ON query_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_query_logs_status     ON query_logs (status);
CREATE INDEX IF NOT EXISTS idx_query_logs_library    ON query_logs (library);
