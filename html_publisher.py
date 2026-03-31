"""
HTMLPublisher: Renders the wiki as a self-contained interactive HTML site.
Completely rewrites the old version to fix:
  - marked.js v9+ API change (Renderer constructor removed)
  - DOMPurify.Config bug
  - Mermaid async rendering race condition
  - Sidebar section matching
"""
import json
from pathlib import Path
from typing import List
from generators.wiki_generator import WikiPage


class HTMLPublisher:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def publish(self, pages: List[WikiPage], repo_name: str) -> str:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        pages_data = [
            {
                "id": self._page_id(p.filename),
                "filename": p.filename,
                "title": p.title,
                "content": p.content,
                "section": self._section(p.filename),
            }
            for p in pages
        ]
        html = self._build_html(pages_data, repo_name)
        out_path = self.output_dir / "index.html"
        out_path.write_text(html, encoding="utf-8")
        return str(out_path)

    def _page_id(self, filename: str) -> str:
        return filename.replace("/", "-").replace(".md", "").replace(".", "-")

    def _section(self, filename: str) -> str:
        if filename == "index.md":          return "Overview"
        if filename == "architecture.md":   return "Architecture"
        if filename == "api-reference.md":  return "API Reference"
        if filename == "data-models.md":    return "Data Models"
        if filename == "infrastructure.md": return "Infrastructure"
        if filename == "dependencies.md":   return "Dependencies"
        if filename.startswith("components/"): return "Components"
        return "Other"

    def _build_html(self, pages: list, repo_name: str) -> str:
        pages_json = json.dumps(pages, ensure_ascii=False, indent=None)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{repo_name} — RepoWiki</title>
<script src="https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.min.js"></script>
<style>
:root{{
  --bg:#fff;--bg2:#f7f8fa;--bg3:#eef0f4;
  --text:#1a1a2e;--text2:#4a5568;--text3:#9aa5b4;
  --border:#dde1e9;--accent:#5b5bd6;--accent2:#7c3aed;
  --green:#16a34a;--orange:#d97706;--red:#dc2626;--blue:#2563eb;--patch:#0891b2;
  --sidebar:260px;--header:52px;
}}
[data-theme=dark]{{
  --bg:#0f0f1a;--bg2:#1a1a2e;--bg3:#252540;
  --text:#e8e8f0;--text2:#a0aec0;--text3:#6272a4;
  --border:#334;--accent:#818cf8;--accent2:#a78bfa;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);height:100vh;display:flex;flex-direction:column;overflow:hidden}}

/* Header */
header{{height:var(--header);background:var(--bg2);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px;padding:0 16px;flex-shrink:0;z-index:100}}
.logo{{font-weight:700;font-size:15px;color:var(--accent);white-space:nowrap}}
.repo-pill{{background:var(--bg3);border:1px solid var(--border);border-radius:20px;padding:3px 12px;font-size:13px;color:var(--text2);white-space:nowrap}}
.search-wrap{{flex:1;max-width:400px;margin:0 auto;position:relative}}
#searchInput{{width:100%;padding:7px 12px 7px 34px;border:1px solid var(--border);border-radius:20px;background:var(--bg3);color:var(--text);font-size:13px;outline:none;transition:border .15s}}
#searchInput:focus{{border-color:var(--accent)}}
.search-icon{{position:absolute;left:11px;top:50%;transform:translateY(-50%);color:var(--text3);font-size:14px;pointer-events:none}}
.search-drop{{position:absolute;top:calc(100% + 4px);left:0;right:0;background:var(--bg);border:1px solid var(--border);border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,.15);max-height:300px;overflow-y:auto;display:none;z-index:999}}
.search-drop.open{{display:block}}
.sr-item{{padding:10px 14px;cursor:pointer;border-bottom:1px solid var(--border);font-size:13px}}
.sr-item:last-child{{border-bottom:none}}
.sr-item:hover{{background:var(--bg3)}}
.sr-title{{font-weight:600;color:var(--text)}}
.sr-excerpt{{color:var(--text3);font-size:11px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.theme-btn{{background:none;border:1px solid var(--border);border-radius:8px;padding:5px 12px;cursor:pointer;color:var(--text2);font-size:13px;white-space:nowrap}}
.theme-btn:hover{{background:var(--bg3)}}

/* Layout */
.layout{{display:flex;flex:1;overflow:hidden}}

/* Sidebar */
aside{{width:var(--sidebar);flex-shrink:0;background:var(--bg2);border-right:1px solid var(--border);overflow-y:auto;padding-bottom:20px}}
.nav-section{{padding:14px 14px 2px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text3)}}
.nav-item{{display:block;padding:7px 14px;font-size:13px;color:var(--text2);cursor:pointer;border-left:3px solid transparent;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:all .12s}}
.nav-item:hover{{background:var(--bg3);color:var(--text)}}
.nav-item.active{{background:var(--bg3);color:var(--accent);border-left-color:var(--accent);font-weight:600}}

/* Content */
main{{flex:1;overflow-y:auto;padding:36px 48px 60px}}

/* Markdown */
.md h1{{font-size:26px;font-weight:700;margin-bottom:8px;line-height:1.2}}
.md h2{{font-size:19px;font-weight:600;margin:28px 0 10px;padding-bottom:7px;border-bottom:1px solid var(--border)}}
.md h3{{font-size:16px;font-weight:600;margin:20px 0 8px;color:var(--text)}}
.md h4{{font-size:14px;font-weight:600;margin:14px 0 6px;color:var(--text2)}}
.md p{{font-size:14px;line-height:1.75;color:var(--text2);margin-bottom:12px}}
.md ul,.md ol{{margin:8px 0 12px 22px}}
.md li{{font-size:14px;line-height:1.7;color:var(--text2);margin-bottom:2px}}
.md a{{color:var(--accent);text-decoration:none}}
.md a:hover{{text-decoration:underline}}
.md blockquote{{border-left:3px solid var(--accent);padding:8px 16px;background:var(--bg2);border-radius:0 8px 8px 0;margin:12px 0}}
.md blockquote p{{margin:0;font-size:13px;color:var(--text2)}}
.md code{{font-family:'SF Mono','Fira Code','Consolas',monospace;font-size:12px;background:var(--bg3);border:1px solid var(--border);border-radius:4px;padding:1px 5px;color:var(--accent2)}}
.md pre{{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:16px;overflow-x:auto;margin:12px 0}}
.md pre code{{background:none;border:none;padding:0;color:var(--text);font-size:13px;line-height:1.6}}
.md table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}}
.md th{{background:var(--bg3);border:1px solid var(--border);padding:8px 12px;text-align:left;font-weight:600;color:var(--text)}}
.md td{{border:1px solid var(--border);padding:7px 12px;color:var(--text2)}}
.md tr:nth-child(even) td{{background:var(--bg2)}}
.md hr{{border:none;border-top:1px solid var(--border);margin:24px 0}}
.md img{{max-width:100%;height:auto}}

/* Method badges */
.badge-get{{display:inline-block;background:#dcfce7;color:#15803d;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700;font-family:monospace}}
.badge-post{{display:inline-block;background:#dbeafe;color:#1d4ed8;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700;font-family:monospace}}
.badge-put{{display:inline-block;background:#fef9c3;color:#854d0e;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700;font-family:monospace}}
.badge-delete{{display:inline-block;background:#fee2e2;color:#991b1b;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700;font-family:monospace}}
.badge-patch{{display:inline-block;background:#e0f2fe;color:#0369a1;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700;font-family:monospace}}

/* Mermaid container */
.mermaid-wrap{{background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:24px 16px;margin:16px 0;overflow-x:auto;text-align:center}}
.mermaid-wrap svg{{max-width:100%;height:auto}}
.mermaid-error{{color:var(--red);font-size:12px;font-family:monospace;white-space:pre-wrap;padding:8px}}

/* Breadcrumb */
.breadcrumb{{font-size:12px;color:var(--text3);margin-bottom:20px}}
.breadcrumb span{{color:var(--accent);cursor:pointer}}
.breadcrumb span:hover{{text-decoration:underline}}

/* Stat cards */
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:16px 0}}
.stat-card{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:14px 16px}}
.stat-v{{font-size:26px;font-weight:700;color:var(--accent)}}
.stat-l{{font-size:12px;color:var(--text3);margin-top:2px}}

@media(max-width:768px){{aside{{display:none}}main{{padding:20px 16px}}}}
</style>
</head>
<body>

<header>
  <div class="logo">📖 RepoWiki</div>
  <div class="repo-pill">{repo_name}</div>
  <div class="search-wrap">
    <span class="search-icon">🔍</span>
    <input id="searchInput" type="text" placeholder="Search docs…" autocomplete="off"/>
    <div class="search-drop" id="searchDrop"></div>
  </div>
  <button class="theme-btn" id="themeBtn" onclick="toggleTheme()">🌙 Dark</button>
</header>

<div class="layout">
  <aside id="sidebar"></aside>
  <main id="content"></main>
</div>

<script>
// ── Data ──────────────────────────────────────────────────────────────────
const PAGES = {pages_json};

// ── Theme ─────────────────────────────────────────────────────────────────
let darkMode = localStorage.getItem('rw-dark') === '1';
function applyTheme() {{
  document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light');
  document.getElementById('themeBtn').textContent = darkMode ? '☀️ Light' : '🌙 Dark';
}}
function toggleTheme() {{
  darkMode = !darkMode;
  localStorage.setItem('rw-dark', darkMode ? '1' : '0');
  applyTheme();
  mermaid.initialize(mermaidConfig());
  renderPage(currentId);
}}
applyTheme();

// ── Mermaid ───────────────────────────────────────────────────────────────
function mermaidConfig() {{
  return {{
    startOnLoad: false,
    theme: darkMode ? 'dark' : 'default',
    securityLevel: 'loose',
    fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif',
    fontSize: 13,
  }};
}}
mermaid.initialize(mermaidConfig());

// ── Router ────────────────────────────────────────────────────────────────
let currentId = (location.hash.slice(1)) || 'index';
if (!PAGES.find(p => p.id === currentId)) currentId = 'index';

function navigate(id) {{
  currentId = id;
  location.hash = id;
  renderSidebar();
  renderPage(id);
}}

window.addEventListener('hashchange', () => {{
  const id = location.hash.slice(1);
  if (id && PAGES.find(p => p.id === id) && id !== currentId) {{
    currentId = id;
    renderSidebar();
    renderPage(id);
  }}
}});

// ── Sidebar ───────────────────────────────────────────────────────────────
const SECTION_ORDER = ['Overview','Architecture','Components','API Reference','Data Models','Infrastructure','Dependencies','Other'];

function renderSidebar() {{
  const groups = {{}};
  PAGES.forEach(p => {{ (groups[p.section] = groups[p.section] || []).push(p); }});
  let html = '';
  SECTION_ORDER.forEach(sec => {{
    if (!groups[sec]) return;
    html += `<div class="nav-section">${{sec}}</div>`;
    groups[sec].forEach(p => {{
      const active = p.id === currentId ? ' active' : '';
      html += `<div class="nav-item${{active}}" onclick="navigate('${{p.id}}')">${{p.title}}</div>`;
    }});
  }});
  document.getElementById('sidebar').innerHTML = html;
}}

// ── Markdown renderer ─────────────────────────────────────────────────────
function mdToHtml(markdown) {{
  // marked v9 uses setOptions differently — use walkTokens for link interception
  const options = {{
    gfm: true,
    breaks: false,
  }};

  // Use marked with a custom renderer via the options object
  const renderer = {{
    link(token) {{
      const href = token.href || '';
      const text = token.text || '';
      if (!href.startsWith('http') && href.endsWith('.md')) {{
        const id = href.replace('../','').replace('.md','').replace('/','--').replace(/--/g,'-');
        return `<a href="#" onclick="navigate('${{id}}');return false;">${{text}}</a>`;
      }}
      return `<a href="${{href}}" target="_blank" rel="noreferrer">${{text}}</a>`;
    }},
    image(token) {{
      const src = token.href || '';
      const alt = token.text || '';
      // Render shields.io badges as inline images
      if (src.includes('shields.io') || src.includes('img.shields.io')) {{
        return `<img src="${{src}}" alt="${{alt}}" style="height:20px;margin:2px 2px;vertical-align:middle;border-radius:3px;display:inline-block">`;
      }}
      return `<img src="${{src}}" alt="${{alt}}" style="max-width:100%">`;
    }}
  }};

  try {{
    return marked.parse(markdown, {{ ...options, renderer }});
  }} catch(e) {{
    // fallback: no custom renderer
    try {{
      return marked.parse(markdown, options);
    }} catch(e2) {{
      return `<pre>${{markdown.replace(/</g,'&lt;')}}</pre>`;
    }}
  }}
}}

// ── Mermaid rendering ─────────────────────────────────────────────────────
let mermaidCounter = 0;

async function renderMermaidBlocks(container) {{
  // Find all <code class="language-mermaid"> blocks that marked generated
  const blocks = container.querySelectorAll('pre code');
  const mermaidBlocks = [];

  blocks.forEach(block => {{
    const text = block.textContent || '';
    const isMermaid = block.className.includes('language-mermaid') ||
      /^(graph |flowchart |sequenceDiagram|erDiagram|classDiagram|gantt|pie |gitGraph)/m.test(text.trim());
    if (isMermaid) mermaidBlocks.push(block);
  }});

  for (const block of mermaidBlocks) {{
    const code = block.textContent.trim();
    const pre = block.closest('pre');
    if (!pre) continue;

    const wrap = document.createElement('div');
    wrap.className = 'mermaid-wrap';

    try {{
      const id = 'mermaid-' + (++mermaidCounter) + '-' + Date.now();
      const {{ svg }} = await mermaid.render(id, code);
      wrap.innerHTML = svg;
    }} catch(err) {{
      wrap.innerHTML = `<div class="mermaid-error">⚠ Diagram error: ${{err.message}}\\n\\n${{code}}</div>`;
    }}
    pre.replaceWith(wrap);
  }}
}}

// ── HTTP method badge injection ───────────────────────────────────────────
function injectBadges(container) {{
  container.querySelectorAll('td').forEach(td => {{
    const t = td.textContent.trim();
    if (/^(GET|POST|PUT|DELETE|PATCH)$/.test(t)) {{
      td.innerHTML = `<span class="badge-${{t.toLowerCase()}}">${{t}}</span>`;
    }}
  }});
  // Also handle the shields.io img tags that might have been stripped
  container.querySelectorAll('img[alt]').forEach(img => {{
    const alt = img.getAttribute('alt') || '';
    if (['GET','POST','PUT','DELETE','PATCH'].includes(alt)) {{
      const span = document.createElement('span');
      span.className = 'badge-' + alt.toLowerCase();
      span.textContent = alt;
      img.replaceWith(span);
    }}
  }});
}}

// ── Page renderer ─────────────────────────────────────────────────────────
async function renderPage(id) {{
  const page = PAGES.find(p => p.id === id) || PAGES[0];
  const el = document.getElementById('content');

  el.innerHTML = '<div style="padding:40px;color:var(--text3);font-size:14px">Rendering…</div>';

  // Breadcrumb
  let crumb = '';
  if (page.section !== 'Overview') {{
    crumb = `<div class="breadcrumb">
      <span onclick="navigate('index')">Home</span> › ${{page.section}} › ${{page.title}}
    </div>`;
  }}

  const rawHtml = mdToHtml(page.content);
  el.innerHTML = crumb + '<div class="md">' + rawHtml + '</div>';

  const mdEl = el.querySelector('.md');
  if (mdEl) {{
    injectBadges(mdEl);
    await renderMermaidBlocks(mdEl);
  }}

  el.scrollTop = 0;
}}

// ── Search ────────────────────────────────────────────────────────────────
const searchInput = document.getElementById('searchInput');
const searchDrop  = document.getElementById('searchDrop');

searchInput.addEventListener('input', () => {{
  const q = searchInput.value.trim().toLowerCase();
  if (!q) {{ searchDrop.classList.remove('open'); return; }}

  const results = [];
  PAGES.forEach(p => {{
    const inTitle   = p.title.toLowerCase().includes(q);
    const inContent = p.content.toLowerCase().includes(q);
    if (!inTitle && !inContent) return;
    let excerpt = '';
    if (inContent) {{
      const idx = p.content.toLowerCase().indexOf(q);
      excerpt = p.content.slice(Math.max(0,idx-40), idx+80).replace(/[#*`>|]/g,'').trim();
    }}
    results.push({{ ...p, excerpt, score: inTitle ? 2 : 1 }});
  }});

  results.sort((a,b) => b.score - a.score);
  const top = results.slice(0, 7);

  if (!top.length) {{
    searchDrop.innerHTML = '<div class="sr-item"><span class="sr-title" style="color:var(--text3)">No results found</span></div>';
  }} else {{
    searchDrop.innerHTML = top.map(r =>
      `<div class="sr-item" onclick="navigate('${{r.id}}');searchInput.value='';searchDrop.classList.remove('open')">
        <div class="sr-title">${{r.title}}</div>
        <div class="sr-excerpt">${{r.excerpt}}</div>
      </div>`
    ).join('');
  }}
  searchDrop.classList.add('open');
}});

document.addEventListener('click', e => {{
  if (!searchInput.contains(e.target) && !searchDrop.contains(e.target))
    searchDrop.classList.remove('open');
}});

searchInput.addEventListener('keydown', e => {{
  if (e.key === 'Escape') {{ searchDrop.classList.remove('open'); searchInput.blur(); }}
}});

// ── Init ──────────────────────────────────────────────────────────────────
renderSidebar();
renderPage(currentId);
</script>
</body>
</html>"""

