// 问答页：会话列表（localStorage）+ 版本选择 + 按 status 分支渲染

const STORAGE_KEY = 'pydocs.conversations';
const $ = (id) => document.getElementById(id);

// 固定展示在输入框上方，覆盖三种判定结果，方便演示
const EXAMPLES = [
  'DataFrame.append 怎么用？',
  'sqlalchemy.orm.Session 怎么创建？',
  '量子计算怎么实现？',
];

const state = {
  conversations: loadConversations(),
  activeId: null,
  libraries: [],
};

/* ---------------- 会话存储 ---------------- */

function loadConversations() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
  } catch (_) {
    return [];
  }
}

function saveConversations() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.conversations.slice(0, 50)));
}

function activeConversation() {
  return state.conversations.find((c) => c.id === state.activeId) || null;
}

function newConversation() {
  const conv = { id: `c${Date.now()}`, title: '新对话', messages: [], createdAt: Date.now() };
  state.conversations.unshift(conv);
  state.activeId = conv.id;
  saveConversations();
  renderSidebar();
  renderMessages();
  setSidebar(false);
}

function deleteConversation(id) {
  state.conversations = state.conversations.filter((c) => c.id !== id);
  if (state.activeId === id) state.activeId = state.conversations[0]?.id || null;
  saveConversations();
  renderSidebar();
  renderMessages();
}

/* ---------------- 手机端会话抽屉 ---------------- */

function setSidebar(open) {
  const sidebar = $('sidebar');
  sidebar.classList.toggle('translate-x-0', open);
  sidebar.classList.toggle('-translate-x-full', !open);
  $('sidebar-backdrop').classList.toggle('hidden', !open);
  $('menu-toggle').setAttribute('aria-expanded', String(open));
}

/* ---------------- 侧边栏 ---------------- */

function renderSidebar() {
  const list = $('conversation-list');
  if (!state.conversations.length) {
    list.innerHTML = '<p class="px-3 py-6 text-xs text-slate-400">还没有对话，点上方「新对话」开始。</p>';
    return;
  }
  list.innerHTML = state.conversations
    .map(
      (c) => `
      <div class="group flex items-center gap-1 rounded-lg px-1 text-sm ${
        c.id === state.activeId ? 'bg-slate-200/70 font-medium' : 'hover:bg-slate-200/40'
      }">
        <button type="button" data-open="${escapeHtml(c.id)}"
          class="min-w-0 flex-1 truncate rounded px-2 py-2 text-left">${escapeHtml(c.title)}</button>
        <button type="button" data-delete="${escapeHtml(c.id)}" aria-label="删除对话：${escapeHtml(c.title)}"
          class="shrink-0 rounded px-1.5 py-1 text-xs text-slate-400 hover:text-rose-600 md:opacity-0 md:group-hover:opacity-100 focus:opacity-100">删除</button>
      </div>`,
    )
    .join('');

  list.querySelectorAll('[data-open]').forEach((el) => {
    el.addEventListener('click', () => {
      state.activeId = el.dataset.open;
      renderSidebar();
      renderMessages();
      setSidebar(false);
    });
  });
  list.querySelectorAll('[data-delete]').forEach((el) => {
    el.addEventListener('click', () => deleteConversation(el.dataset.delete));
  });
}

/* ---------------- 版本选择 ---------------- */

async function loadLibraries() {
  try {
    const data = await request('/api/v1/versions');
    state.libraries = data.libraries;
  } catch (_) {
    state.libraries = [];
  }
  const libSelect = $('library-select');
  libSelect.innerHTML =
    '<option value="">全部库</option>' +
    state.libraries
      .map((l) => `<option value="${escapeHtml(l.library)}">${escapeHtml(l.library)}</option>`)
      .join('');
  refreshVersionOptions();
}

function refreshVersionOptions() {
  const library = $('library-select').value;
  const versionSelect = $('version-select');
  const lib = state.libraries.find((l) => l.library === library);

  if (!lib) {
    versionSelect.innerHTML = '<option value="">不指定（跨版本比对）</option>';
    versionSelect.disabled = true;
    versionSelect.title = '先选择具体库才能指定版本';
    return;
  }
  versionSelect.disabled = false;
  versionSelect.title = '';
  versionSelect.innerHTML =
    '<option value="">不指定（跨版本比对）</option>' +
    lib.versions
      .map(
        (v) =>
          `<option value="${escapeHtml(v.version)}">${escapeHtml(v.version)}（${v.indexed_chunks} 块）</option>`,
      )
      .join('');
}

/* ---------------- 消息渲染 ---------------- */

const STATUS_STYLE = {
  answer: { label: '答案', cls: 'bg-emerald-100 text-emerald-700' },
  conflict: { label: '版本冲突', cls: 'bg-amber-100 text-amber-700' },
  refused: { label: '已拒答', cls: 'bg-slate-200 text-slate-600' },
  error: { label: '请求失败', cls: 'bg-rose-100 text-rose-700' },
};

function citationChip(c) {
  const label = `${c.version ?? ''}·${c.symbol ?? ''}`;
  const href = c.source_url || '#';
  const missing = c.doc_type === 'missing';
  return `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer"
    class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${
      missing
        ? 'border-rose-200 bg-rose-50 text-rose-700'
        : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-400'
    }">${missing ? '✕' : '↗'} ${escapeHtml(label)}</a>`;
}

function conflictCard(conflict) {
  const claims = (conflict.claims || [])
    .map((claim) => {
      const state = !claim.exists ? '该版本不存在' : claim.deprecated ? '已弃用' : '可用';
      const stateCls = !claim.exists
        ? 'bg-rose-100 text-rose-700'
        : claim.deprecated
          ? 'bg-amber-100 text-amber-700'
          : 'bg-emerald-100 text-emerald-700';
      return `<div class="rounded-lg border border-slate-200 bg-white p-3">
          <div class="flex items-center gap-2">
            <span class="rounded bg-slate-900 px-1.5 py-0.5 text-xs font-medium text-white">${escapeHtml(claim.version)}</span>
            <span class="rounded px-1.5 py-0.5 text-xs ${stateCls}">${state}</span>
          </div>
          <p class="mt-2 text-sm leading-relaxed text-slate-700">${escapeHtml((claim.text || '').slice(0, 400))}</p>
          ${claim.deprecation_note ? `<p class="mt-1 text-xs text-amber-700">弃用说明：${escapeHtml(claim.deprecation_note.slice(0, 200))}</p>` : ''}
          <a href="${escapeHtml(claim.source_url || '#')}" target="_blank" rel="noreferrer"
             class="mt-1 inline-block break-all text-xs text-blue-600 underline">${escapeHtml(claim.source_url || '')}</a>
        </div>`;
    })
    .join('');

  return `<div class="mt-2 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
      <p class="text-sm font-medium text-amber-800">${escapeHtml(conflict.symbol)} 在不同版本间不一致</p>
      <ul class="mt-1 space-y-0.5 text-xs text-amber-700">
        ${(conflict.reasons || []).map((r) => `<li>• ${escapeHtml(r)}</li>`).join('')}
      </ul>
      <div class="mt-2 grid gap-2 md:grid-cols-2">${claims}</div>
      <p class="mt-2 text-xs text-slate-500">系统不替你选择版本：请确认你使用的版本后再提问。</p>
    </div>`;
}

function assistantBubble(msg, index) {
  const style = STATUS_STYLE[msg.status] || STATUS_STYLE.answer;
  const meta = msg.meta || {};
  const metaLine = [
    meta.versions?.length ? `版本：${meta.versions.join(', ')}` : '',
    meta.top_vector_score != null ? `相似度：${Number(meta.top_vector_score).toFixed(3)}` : '',
    meta.threshold ? `阈值：${meta.threshold}` : '',
    meta.mode ? `过滤：${meta.mode}` : '',
    meta.elapsed_ms ? formatMs(meta.elapsed_ms) : '',
  ]
    .filter(Boolean)
    .join(' · ');

  // 退化为文档摘录时要明确告诉用户：答案未经模型改写
  const extractiveBadge =
    msg.status === 'answer' && meta.used_llm === false
      ? '<span title="未调用大模型：答案是检索到的文档原文摘录，未经改写" class="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700">文档摘录（未调用模型）</span>'
      : '';

  const conflicts = (msg.conflicts || []).map(conflictCard).join('');
  const reasons = (msg.reasons || []).length
    ? `<ul class="mt-2 space-y-0.5 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
         ${msg.reasons.map((r) => `<li>• ${escapeHtml(r)}</li>`).join('')}
       </ul>`
    : '';
  const citations = (msg.citations || []).length
    ? `<div class="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-2">
         <span class="text-xs text-slate-400">来源：</span>
         ${msg.citations.map(citationChip).join('')}
       </div>`
    : '';
  const copyBtn = msg.answer
    ? `<button type="button" data-copy-msg="${index}" data-label="复制回答"
         class="ml-auto rounded border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500 hover:border-slate-400">复制回答</button>`
    : '';

  return `<div class="max-w-[92%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div class="mb-1 flex flex-wrap items-center gap-2">
        <span class="rounded px-1.5 py-0.5 text-xs font-medium ${style.cls}">${style.label}</span>
        ${extractiveBadge}
        ${copyBtn}
      </div>
      <div class="msg-body text-sm leading-relaxed text-slate-800">${renderMarkdown(msg.answer)}</div>
      ${conflicts}${reasons}${citations}
      ${metaLine ? `<p class="mt-2 text-[11px] text-slate-400">${escapeHtml(metaLine)}</p>` : ''}
    </div>`;
}

function userBubble(content) {
  return `<div class="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-slate-900 px-4 py-2.5 text-white">
      <div class="whitespace-pre-wrap break-words text-sm">${escapeHtml(content)}</div>
    </div>`;
}

function renderMessages() {
  const box = $('messages');
  const conv = activeConversation();
  if (!conv || !conv.messages.length) {
    box.innerHTML = `
      <div class="grid h-full place-items-center text-center">
        <div class="max-w-md px-4">
          <p class="text-lg font-semibold text-slate-700">Python 版本感知文档问答</p>
          <p class="mt-1 text-sm text-slate-500">同一问题在不同版本下答案可能不同。系统会标注来源版本，跨版本冲突时不合并、证据不足时拒答。</p>
          <p class="mt-3 text-xs text-slate-400">输入框上方有三个示例，分别演示冲突、正常回答和拒答。</p>
        </div>
      </div>`;
    return;
  }

  box.innerHTML = conv.messages
    .map((m, i) => (m.role === 'user' ? userBubble(m.content) : assistantBubble(m, i)))
    .join('');
  highlightAll(box);
  box.scrollTop = box.scrollHeight;
}

/** 点击复制按钮：成功/失败都在按钮上短暂提示 */
function flashButton(btn, label) {
  const original = btn.dataset.label || btn.textContent;
  btn.dataset.label = original;
  btn.textContent = label;
  setTimeout(() => {
    btn.textContent = original;
  }, 1500);
}

/* ---------------- 提问 ---------------- */

async function ask() {
  const input = $('chat-input');
  const text = input.value.trim();
  if (!text) return;

  if (!state.activeId) newConversation();
  const conv = activeConversation();
  conv.messages.push({ role: 'user', content: text });
  conv.title = conv.title === '新对话' ? text.slice(0, 20) : conv.title;
  input.value = '';
  renderSidebar();
  renderMessages();

  // 检索 + 生成通常要几秒，显示已等待时间，避免用户以为页面卡住
  const started = Date.now();
  const pending = document.createElement('div');
  pending.setAttribute('role', 'status');
  pending.className = 'max-w-[60%] rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-400';
  const tick = () => {
    const sec = Math.floor((Date.now() - started) / 1000);
    pending.textContent = `检索文档并生成回答… 已等待 ${sec}s`;
  };
  tick();
  const timer = setInterval(tick, 1000);
  $('messages').appendChild(pending);
  $('messages').scrollTop = $('messages').scrollHeight;

  const submit = $('chat-submit');
  submit.disabled = true;
  const payload = {
    query: text,
    library: $('library-select').value || null,
    version: $('version-select').value || null,
    mode: $('mode-select').value,
    top_k: 4,
  };

  try {
    const data = await postJson('/api/v1/query', payload);
    conv.messages.push({ role: 'assistant', ...data });
  } catch (err) {
    conv.messages.push({
      role: 'assistant',
      status: 'error',
      answer: `请求失败：${err.message}`,
      reasons: [],
      citations: [],
      conflicts: [],
      meta: {},
    });
  } finally {
    clearInterval(timer);
    saveConversations();
    renderMessages();
    pending.remove();
    submit.disabled = false;
    input.focus();
  }
}

/* ---------------- 初始化 ---------------- */

function renderQuickAsks() {
  $('quick-asks').innerHTML =
    '<span class="self-center text-slate-400">试试：</span>' +
    EXAMPLES.map(
      (q) =>
        `<button type="button" class="example rounded-full border border-slate-300 bg-white px-3 py-1 hover:border-slate-500">${escapeHtml(q)}</button>`,
    ).join('');
}

function bindEvents() {
  $('new-chat').addEventListener('click', newConversation);
  $('library-select').addEventListener('change', refreshVersionOptions);
  $('menu-toggle').addEventListener('click', () => setSidebar($('sidebar').classList.contains('-translate-x-full')));
  $('sidebar-backdrop').addEventListener('click', () => setSidebar(false));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') setSidebar(false);
  });

  $('quick-asks').addEventListener('click', (e) => {
    const btn = e.target.closest('.example');
    if (!btn) return;
    $('chat-input').value = btn.textContent;
    $('chat-input').focus();
  });

  // 复制：回答按钮读取对应消息，代码块按钮读取同一代码块的文本
  $('messages').addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-copy-msg], button.copy-code');
    if (!btn) return;
    let text = '';
    if (btn.dataset.copyMsg !== undefined) {
      text = activeConversation()?.messages[Number(btn.dataset.copyMsg)]?.answer || '';
    } else {
      text = btn.closest('pre')?.querySelector('code')?.textContent || '';
    }
    const ok = await copyText(text);
    flashButton(btn, ok ? '已复制' : '复制失败');
  });

  $('chat-form').addEventListener('submit', (e) => {
    e.preventDefault();
    ask();
  });
  $('chat-input').addEventListener('keydown', (e) => {
    // 中文输入法选词时的回车不应发送（e.isComposing 为 true）
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      ask();
    }
  });
}

async function init() {
  bindEvents();
  renderQuickAsks();
  await loadLibraries();
  if (state.conversations.length) state.activeId = state.conversations[0].id;
  renderSidebar();
  renderMessages();
}

init();
