// 管理页：索引状态 + 评测结果

const $ = (id) => document.getElementById(id);

const MODE_LABEL = { pre: 'pre（先过滤）', post: 'post（先召回）', none: 'none（不过滤）' };

function num(value, digits = 3) {
  return typeof value === 'number' ? value.toFixed(digits) : '—';
}

async function loadStatus() {
  try {
    const status = await request('/api/v1/index/status');
    $('stat-chunks').textContent = status.total_chunks ?? '—';
    $('stat-dim').textContent = status.dim ?? '—';
    return status;
  } catch (err) {
    $('stat-chunks').textContent = '不可用';
    throw err;
  }
}

async function loadVersions() {
  const data = await request('/api/v1/versions');
  const rows = data.libraries
    .map(
      (lib) => `
      <tr class="border-b border-slate-100">
        <td class="py-2 pr-4 font-medium">${escapeHtml(lib.library)}</td>
        <td class="py-2">
          <div class="flex flex-wrap gap-2">
            ${lib.versions
              .map(
                (v) => `<span class="rounded-md border px-2 py-0.5 text-xs ${
                  v.indexed_chunks > 0
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                    : 'border-slate-200 bg-slate-50 text-slate-400'
                }">${escapeHtml(v.version)} · ${v.indexed_chunks} 块</span>`,
              )
              .join('')}
          </div>
        </td>
      </tr>`,
    )
    .join('');
  $('version-table').innerHTML = `<table class="w-full text-sm">
      <thead class="text-xs uppercase tracking-wide text-slate-500">
        <tr><th class="py-2 pr-4 text-left">库</th><th class="py-2 text-left">版本</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function loadEval() {
  let data;
  try {
    data = await request('/api/v1/eval/results');
  } catch (err) {
    $('eval-meta').textContent = '尚未运行评测';
    $('eval-badge').textContent = '无数据';
    const box = $('eval-error');
    box.classList.remove('hidden');
    box.textContent = `读取评测失败：${err.message}。请先执行 python backend/scripts/run_eval.py`;
    return;
  }

  $('stat-threshold').textContent = num(data.threshold, 2);
  $('eval-meta').textContent = `生成于 ${data.generated_at} · ${data.cases} 道题 · Top-${data.top_k} · 嵌入 ${data.embedding_model} · 生成模型 ${data.llm_model}`;

  const best = Math.max(...Object.values(data.modes).map((m) => m.status_accuracy ?? 0));
  const badge = $('eval-badge');
  badge.textContent = `状态准确率最高 ${best.toFixed(3)}`;
  badge.className =
    best >= 0.95
      ? 'rounded-full bg-emerald-100 px-3 py-1 text-xs text-emerald-700'
      : best >= 0.8
        ? 'rounded-full bg-amber-100 px-3 py-1 text-xs text-amber-700'
        : 'rounded-full bg-rose-100 px-3 py-1 text-xs text-rose-700';

  $('eval-modes').innerHTML = Object.entries(data.modes)
    .map(
      ([mode, m]) => `<tr>
        <td class="py-2 pr-4 font-medium">${MODE_LABEL[mode] || escapeHtml(mode)}</td>
        <td class="py-2 pr-4">${num(m.recall_at_k)} <span class="text-xs text-slate-400">(n=${m.recall_evaluated})</span></td>
        <td class="py-2 pr-4">${num(m.status_accuracy)}</td>
        <td class="py-2 pr-4">${num(m.conflict_rate)}</td>
        <td class="py-2 pr-4">${num(m.refusal_rate)}</td>
      </tr>`,
    )
    .join('');

  // Recall@K 横向条形图：三种过滤方式并排比较（纯 CSS，无图表库）
  $('eval-chart').innerHTML =
    `<p class="text-xs text-slate-500">Recall@${escapeHtml(data.top_k)} 对比（越高越好）。none 覆盖率最高，但会把其他版本的答案混进来，所以默认用 pre。</p>` +
    Object.entries(data.modes)
      .map(([mode, m]) => {
        const value = typeof m.recall_at_k === 'number' ? m.recall_at_k : 0;
        return `<div class="flex items-center gap-3 text-sm">
          <span class="w-28 shrink-0 text-slate-600">${MODE_LABEL[mode] || escapeHtml(mode)}</span>
          <div class="h-3 flex-1 overflow-hidden rounded-full bg-slate-100" role="img" aria-label="${MODE_LABEL[mode] || escapeHtml(mode)} Recall ${value.toFixed(3)}">
            <div class="h-full rounded-full ${mode === 'pre' ? 'bg-emerald-600' : 'bg-slate-400'}" style="width: ${(value * 100).toFixed(1)}%"></div>
          </div>
          <span class="w-14 text-right tabular-nums">${value.toFixed(3)}</span>
        </div>`;
      })
      .join('');

  const errors = data.errors || {};
  const cards = [
    ['冲突误报', errors.conflict_false_positive, '期望正常回答却返回冲突'],
    ['冲突漏报', errors.conflict_missed, '期望冲突却没识别出来'],
    ['误拒答', errors.false_refusal, '期望回答却拒答'],
  ];
  $('eval-errors').innerHTML = cards
    .map(
      ([label, value, hint]) => `<div class="rounded-lg border border-slate-200 p-3">
        <p class="text-xs text-slate-500">${label}</p>
        <p class="mt-1 text-xl font-semibold ${value > 0 ? 'text-rose-600' : 'text-emerald-600'}">${value ?? '—'}</p>
        <p class="mt-0.5 text-xs text-slate-400">${hint}</p>
      </div>`,
    )
    .join('');

  const rows = (data.details || [])
    .map((d) => {
      const ok = d.status_ok;
      return `<tr class="border-b border-slate-100 ${ok ? '' : 'bg-rose-50'}">
        <td class="py-1.5 pr-2 font-mono text-xs">${escapeHtml(d.id)}</td>
        <td class="py-1.5 pr-2">${escapeHtml(d.query)}</td>
        <td class="py-1.5 pr-2 text-xs text-slate-500">${escapeHtml(d.version || '未指定')}</td>
        <td class="py-1.5 pr-2 text-xs">${escapeHtml(d.expect_status)} → ${escapeHtml(d.actual_status)}</td>
        <td class="py-1.5 pr-2 text-xs">${d.recall_hit === null ? '—' : d.recall_hit ? '命中' : '未命中'}</td>
        <td class="py-1.5 text-xs text-slate-500">${num(d.top_score)}</td>
      </tr>`;
    })
    .join('');
  $('eval-details').innerHTML = `<table class="w-full text-left text-sm">
      <thead class="sticky top-0 bg-white text-xs uppercase tracking-wide text-slate-500">
        <tr><th class="py-2 pr-2">ID</th><th class="py-2 pr-2">问题</th><th class="py-2 pr-2">版本</th>
        <th class="py-2 pr-2">状态</th><th class="py-2 pr-2">召回</th><th class="py-2">相似度</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

const STATUS_BADGE = {
  answer: 'bg-emerald-100 text-emerald-700',
  conflict: 'bg-amber-100 text-amber-700',
  refused: 'bg-slate-200 text-slate-600',
};

async function loadLogs() {
  const meta = $('logs-meta');
  const errBox = $('logs-error');
  try {
    const data = await request('/api/v1/query/logs?limit=20');
    errBox.classList.add('hidden');

    const s = data.summary || {};
    meta.textContent = s.total
      ? `累计 ${s.total} 次查询 · 最后一条 ${s.last_at}`
      : '还没有查询记录，去问答页问一句就会出现在这里';

    $('logs-metrics').innerHTML = [
      ['总查询', s.total ?? 0],
      ['正常回答', s.answered ?? 0],
      ['冲突', s.conflicted ?? 0],
      ['拒答率', s.refusal_rate == null ? '—' : s.refusal_rate.toFixed(2)],
    ]
      .map(
        ([label, value]) => `<div class="rounded-lg border border-slate-200 p-3">
            <p class="text-xs text-slate-500">${label}</p>
            <p class="mt-1 text-xl font-semibold">${value}</p>
          </div>`,
      )
      .join('');

    if (!data.items.length) {
      $('logs-table').innerHTML = '<p class="text-sm text-slate-400">暂无记录</p>';
      return;
    }

    $('logs-table').innerHTML = `<table class="w-full text-left text-sm">
        <thead class="sticky top-0 bg-white text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th class="py-2 pr-2">时间</th><th class="py-2 pr-2">问题</th>
            <th class="py-2 pr-2">范围</th><th class="py-2 pr-2">状态</th>
            <th class="py-2 pr-2">相似度</th><th class="py-2">耗时</th>
          </tr>
        </thead>
        <tbody>
          ${data.items
            .map(
              (it) => `<tr class="border-b border-slate-100">
              <td class="py-1.5 pr-2 text-xs text-slate-500">${escapeHtml((it.created_at || '').replace('T', ' ').slice(5, 19))}</td>
              <td class="py-1.5 pr-2">${escapeHtml(it.question)}</td>
              <td class="py-1.5 pr-2 text-xs text-slate-500">${escapeHtml(it.library || '全部')} · ${escapeHtml(it.request_version || '未指定')} · ${escapeHtml(it.mode)}</td>
              <td class="py-1.5 pr-2"><span class="rounded px-1.5 py-0.5 text-xs ${STATUS_BADGE[it.status] || ''}">${escapeHtml(it.status)}</span></td>
              <td class="py-1.5 pr-2 text-xs">${it.top_score == null ? '—' : Number(it.top_score).toFixed(3)}</td>
              <td class="py-1.5 text-xs text-slate-500">${it.elapsed_ms == null ? '—' : `${it.elapsed_ms} ms`}</td>
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>`;
  } catch (err) {
    meta.textContent = '读取失败';
    $('logs-metrics').innerHTML = '';
    $('logs-table').innerHTML = '';
    errBox.classList.remove('hidden');
    errBox.textContent = `查询日志不可用：${err.message}（确认 Docker 中的 PostgreSQL 已启动，并执行过 backend/scripts/init_db.py）`;
  }
}

async function init() {
  try {
    await loadStatus();
  } catch (_) {
    /* 错误已体现在卡片上 */
  }
  await Promise.all([loadVersions().catch(() => {}), loadEval(), loadLogs()]);
  $('logs-refresh').addEventListener('click', loadLogs);
}

init();
