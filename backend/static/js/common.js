// 公共工具：请求封装、文本渲染、代码高亮、复制。问答页与管理页共用。

/** HTML 转义：所有来自后端/文档的文本必须先经过这里再插入 DOM */
function escapeHtml(text) {
  return String(text ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

/** 统一请求：非 2xx 时抛出后端 detail，页面能直接看到失败原因 */
async function request(url, options = {}) {
  const res = await fetch(url, options);
  const isJson = (res.headers.get('content-type') || '').includes('application/json');
  const body = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = isJson && body.detail ? body.detail : `请求失败（HTTP ${res.status}）`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return body;
}

function postJson(url, payload) {
  return request(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/**
 * 复制文本。navigator.clipboard 只在 HTTPS 或 localhost 下可用，
 * 部署到普通 HTTP 地址时回退到 execCommand。
 */
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) {
    /* 落到下面的回退方案 */
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch (_) {
    ok = false;
  }
  area.remove();
  return ok;
}

/**
 * 极简 Markdown 渲染（先转义再解析，防 XSS）：
 * 代码块、行内代码、加粗、链接、无序列表、三级标题、换行。
 */
function renderMarkdown(text) {
  const blocks = String(text ?? '').split(/```/);
  return blocks
    .map((block, index) => {
      // 奇数块是围栏代码
      if (index % 2 === 1) {
        const lines = block.replace(/^\n/, '').split('\n');
        const first = lines[0].trim();
        const lang = /^[a-zA-Z0-9+#_-]+$/.test(first) ? lines.shift().trim() : '';
        const code = escapeHtml(lines.join('\n'));
        return `<pre class="code-block relative my-2 rounded-lg bg-slate-900 p-3 pt-8 text-xs leading-relaxed text-slate-100 overflow-x-auto"><code class="language-${lang || 'plaintext'}">${code}</code></pre>`;
      }
      return escapeHtml(block)
        .replace(/`([^`\n]+)`/g, '<code class="rounded bg-slate-100 px-1 py-0.5 text-[0.8em] text-rose-600">$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a class="text-blue-600 underline break-all" href="$2" target="_blank" rel="noreferrer">$1</a>')
        // 裸 URL 也可点击
        .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a class="text-blue-600 underline break-all" href="$2" target="_blank" rel="noreferrer">$2</a>')
        .replace(/^### (.+)$/gm, '<h3 class="mt-3 mb-1 font-semibold">$1</h3>')
        .replace(/^[-*] (.+)$/gm, '<li class="ml-4 list-disc">$1</li>')
        .replace(/\n/g, '<br />');
    })
    .join('');
}

/** 渲染后高亮代码块，并给每个代码块加一个复制按钮 */
function highlightAll(root) {
  root.querySelectorAll('pre code').forEach((el) => {
    try { window.hljs?.highlightElement(el); } catch (_) { /* 高亮失败不影响阅读 */ }
  });
  root.querySelectorAll('.code-block').forEach((pre) => {
    if (pre.querySelector('.copy-code')) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className =
      'copy-code absolute right-2 top-2 rounded bg-slate-700 px-2 py-0.5 text-[11px] text-slate-100 hover:bg-slate-600';
    btn.dataset.label = '复制';
    btn.textContent = '复制';
    pre.appendChild(btn);
  });
}

function formatMs(ms) {
  return typeof ms === 'number' ? `${ms} ms` : '';
}
