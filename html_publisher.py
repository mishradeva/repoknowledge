"""
HTMLPublisher: Renders the wiki as a self-contained interactive HTML site.

One output file: docs/wiki/index.html
Features:
  - Sidebar navigation with collapsible sections
  - Live search across all pages
  - Mermaid diagram rendering (loaded from CDN)
  - Syntax-highlighted code blocks
  - Tech stack badges
  - Dark/light mode toggle
  - Zero external dependencies beyond CDN scripts (works offline with cached CDN)
  - All pages embedded as JSON — no server needed, pure static
"""
import json
from pathlib import Path
from typing import List
from generators.wiki_generator import WikiPage


class HTMLPublisher:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def publish(self, pages: List[WikiPage], repo_name: str) -> str:
        """Write a single index.html containing all wiki pages. Returns output path."""
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
        if filename == "index.md":
            return "overview"
        if filename.startswith("components/"):
            return "components"
        return filename.replace(".md", "").replace("-", " ").title()

    def _build_html(self, pages: list, repo_name: str) -> str:
        pages_json = json.dumps(pages, ensure_ascii=False)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{repo_name} — RepoWiki</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify/dist/purify.min.js"></script>
<style>
  :root {{
    --bg: #ffffff;
    --bg2: #f6f7f9;
    --bg3: #eef0f3;
    --text: #1a1a2e;
    --text2: #4a4a6a;
    --text3: #7a7a9a;
    --border: #d0d4dc;
    --accent: #5b5bd6;
    --accent2: #7c3aed;
    --sidebar-w: 260px;
    --header-h: 52px;
    --success: #16a34a;
    --warning: #d97706;
    --danger: #dc2626;
  }}
  [data-theme="dark"] {{
    --bg: #0f0f1a;
    --bg2: #1a1a2e;
    --bg3: #252540;
    --text: #e8e8f0;
    --text2: #a8a8c8;
    --text3: #6868a8;
    --border: #33335a;
    --accent: #7c7cf0;
    --accent2: #a78bfa;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--text);
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }}

  /* ---- Header ---- */
  header {{
    height: var(--header-h);
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    padding: 0 16px;
    gap: 12px;
    flex-shrink: 0;
    z-index: 100;
  }}
  .logo {{
    font-weight: 700;
    font-size: 15px;
    color: var(--accent);
    white-space: nowrap;
  }}
  .repo-name {{
    font-weight: 500;
    font-size: 14px;
    color: var(--text2);
    white-space: nowrap;
  }}
  .search-wrap {{
    flex: 1;
    max-width: 420px;
    margin: 0 auto;
    position: relative;
  }}
  #search {{
    width: 100%;
    padding: 7px 12px 7px 32px;
    border: 1px solid var(--border);
    border-radius: 20px;
    background: var(--bg3);
    color: var(--text);
    font-size: 13px;
    outline: none;
  }}
  #search:focus {{ border-color: var(--accent); }}
  .search-icon {{
    position: absolute;
    left: 10px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--text3);
    font-size: 13px;
  }}
  .search-results {{
    position: absolute;
    top: calc(100% + 4px);
    left: 0; right: 0;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.12);
    max-height: 320px;
    overflow-y: auto;
    display: none;
    z-index: 200;
  }}
  .search-results.open {{ display: block; }}
  .search-result-item {{
    padding: 10px 14px;
    cursor: pointer;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
  }}
  .search-result-item:hover {{ background: var(--bg3); }}
  .search-result-item:last-child {{ border-bottom: none; }}
  .search-result-title {{ font-weight: 500; color: var(--text); }}
  .search-result-excerpt {{ color: var(--text3); font-size: 12px; margin-top: 2px; }}
  .theme-toggle {{
    background: none;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 10px;
    cursor: pointer;
    color: var(--text2);
    font-size: 13px;
    white-space: nowrap;
  }}

  /* ---- Layout ---- */
  .layout {{
    display: flex;
    flex: 1;
    overflow: hidden;
  }}

  /* ---- Sidebar ---- */
  nav {{
    width: var(--sidebar-w);
    flex-shrink: 0;
    background: var(--bg2);
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 12px 0;
  }}
  .nav-section-label {{
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text3);
    padding: 14px 16px 4px;
  }}
  .nav-item {{
    display: block;
    padding: 7px 16px;
    cursor: pointer;
    font-size: 13px;
    color: var(--text2);
    text-decoration: none;
    border-left: 3px solid transparent;
    transition: all 0.15s;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .nav-item:hover {{ background: var(--bg3); color: var(--text); }}
  .nav-item.active {{
    background: var(--bg3);
    color: var(--accent);
    border-left-color: var(--accent);
    font-weight: 500;
  }}

  /* ---- Main content ---- */
  main {{
    flex: 1;
    overflow-y: auto;
    padding: 36px 48px;
    max-width: 900px;
  }}

  /* ---- Markdown styles ---- */
  .md h1 {{ font-size: 26px; font-weight: 700; margin-bottom: 6px; color: var(--text); }}
  .md h2 {{ font-size: 20px; font-weight: 600; margin: 28px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border); color: var(--text); }}
  .md h3 {{ font-size: 16px; font-weight: 600; margin: 20px 0 8px; color: var(--text); }}
  .md h4 {{ font-size: 14px; font-weight: 600; margin: 16px 0 6px; color: var(--text2); }}
  .md p {{ line-height: 1.7; margin-bottom: 12px; color: var(--text2); font-size: 14px; }}
  .md ul, .md ol {{ margin: 8px 0 12px 20px; }}
  .md li {{ line-height: 1.7; color: var(--text2); font-size: 14px; margin-bottom: 2px; }}
  .md a {{ color: var(--accent); text-decoration: none; }}
  .md a:hover {{ text-decoration: underline; }}
  .md blockquote {{
    border-left: 3px solid var(--accent);
    padding: 8px 16px;
    background: var(--bg2);
    border-radius: 0 6px 6px 0;
    margin: 12px 0;
    color: var(--text2);
    font-size: 13px;
  }}
  .md code {{
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 1px 5px;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 12px;
    color: var(--accent2);
  }}
  .md pre {{
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    overflow-x: auto;
    margin: 12px 0;
  }}
  .md pre code {{
    background: none;
    border: none;
    padding: 0;
    color: var(--text);
    font-size: 13px;
    line-height: 1.6;
  }}
  .md table {{
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 13px;
  }}
  .md th {{
    background: var(--bg3);
    border: 1px solid var(--border);
    padding: 8px 12px;
    text-align: left;
    font-weight: 600;
    color: var(--text);
  }}
  .md td {{
    border: 1px solid var(--border);
    padding: 7px 12px;
    color: var(--text2);
  }}
  .md tr:nth-child(even) td {{ background: var(--bg2); }}
  .md img[src*="shields.io"] {{
    height: 20px;
    margin: 2px 2px;
    vertical-align: middle;
    border-radius: 3px;
  }}
  .md hr {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 24px 0;
  }}

  /* ---- Mermaid diagrams ---- */
  .mermaid-wrap {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    margin: 16px 0;
    overflow-x: auto;
    text-align: center;
  }}
  .mermaid-wrap svg {{ max-width: 100%; }}

  /* ---- Stats cards ---- */
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin: 16px 0;
  }}
  .stat-card {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
  }}
  .stat-value {{ font-size: 26px; font-weight: 700; color: var(--accent); }}
  .stat-label {{ font-size: 12px; color: var(--text3); margin-top: 2px; }}

  /* ---- Breadcrumb ---- */
  .breadcrumb {{
    font-size: 12px;
    color: var(--text3);
    margin-bottom: 20px;
  }}
  .breadcrumb span {{ cursor: pointer; color: var(--accent); }}
  .breadcrumb span:hover {{ text-decoration: underline; }}

  /* ---- Loading ---- */
  .loading {{
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--text3);
    font-size: 14px;
  }}

  @media (max-width: 768px) {{
    nav {{ display: none; }}
    main {{ padding: 20px 16px; }}
  }}
</style>
</head>
<body>

<header>
  <div class="logo">📖 RepoWiki</div>
  <div class="repo-name">/ {repo_name}</div>
  <div class="search-wrap">
    <span class="search-icon">🔍</span>
    <input id="search" type="text" placeholder="Search wiki..."/>
    <div class="search-results" id="searchResults"></div>
  </div>
  <button class="theme-toggle" onclick="toggleTheme()">🌙 Dark</button>
</header>

<div class="layout">
  <nav id="sidebar"></nav>
  <main id="content"><div class="loading">Loading wiki...</div></main>
</div>

<script>
const PAGES = {pages_json};

// ---- Theme ----
let dark = localStorage.getItem('rw-theme') === 'dark';
function applyTheme() {{
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.querySelector('.theme-toggle').textContent = dark ? '☀️ Light' : '🌙 Dark';
}}
function toggleTheme() {{
  dark = !dark;
  localStorage.setItem('rw-theme', dark ? 'dark' : 'light');
  applyTheme();
  // Re-init mermaid for dark/light
  initMermaid();
  renderCurrentPage();
}}
applyTheme();

// ---- Mermaid ----
function initMermaid() {{
  mermaid.initialize({{
    startOnLoad: false,
    theme: dark ? 'dark' : 'default',
    securityLevel: 'loose',
    fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif',
  }});
}}
initMermaid();

// ---- Router ----
let currentPageId = 'index';

function getPageById(id) {{
  return PAGES.find(p => p.id === id) || PAGES[0];
}}

function navigate(id) {{
  currentPageId = id;
  renderCurrentPage();
  renderSidebar();
  window.history.pushState({{page: id}}, '', '#' + id);
}}

window.addEventListener('popstate', (e) => {{
  if (e.state && e.state.page) navigate(e.state.page);
}});

// Pick initial page from hash
const hashId = window.location.hash.slice(1);
if (hashId && PAGES.find(p => p.id === hashId)) currentPageId = hashId;

// ---- Sidebar ----
function renderSidebar() {{
  const sections = {{}};
  PAGES.forEach(p => {{
    sections[p.section] = sections[p.section] || [];
    sections[p.section].push(p);
  }});

  const sectionOrder = ['overview', 'Architecture', 'components', 'Api Reference',
    'Data Models', 'Infrastructure', 'Dependencies'];

  let html = '';
  const allSections = [...new Set([...sectionOrder, ...Object.keys(sections)])];
  allSections.forEach(sec => {{
    if (!sections[sec]) return;
    const label = sec === 'overview' ? 'Overview' :
                  sec === 'components' ? 'Components' : sec;
    html += `<div class="nav-section-label">${{label}}</div>`;
    sections[sec].forEach(p => {{
      const active = p.id === currentPageId ? 'active' : '';
      html += `<a class="nav-item ${{active}}" onclick="navigate('${{p.id}}')">${{p.title}}</a>`;
    }});
  }});
  document.getElementById('sidebar').innerHTML = html;
}}

// ---- Content renderer ----
async function renderCurrentPage() {{
  const page = getPageById(currentPageId);
  const el = document.getElementById('content');
  el.innerHTML = '<div class="loading">Rendering...</div>';

  // Intercept markdown links → navigate
  const renderer = new marked.Renderer();
  renderer.link = (href, title, text) => {{
    const isLocal = href && !href.startsWith('http') && href.endsWith('.md');
    if (isLocal) {{
      const targetId = href.replace('../', '').replace('.md', '').replace('/', '-');
      return `<a href="#" onclick="navigate('${{targetId}}');return false;">${{text}}</a>`;
    }}
    return `<a href="${{href}}" target="_blank" rel="noreferrer">${{text}}</a>`;
  }};

  marked.setOptions({{ renderer, breaks: true, gfm: true }});

  // Convert markdown to HTML
  const rawHtml = marked.parse(page.content || '');
  const safeHtml = typeof DOMPurify !== 'undefined'
    ? DOMPurify.sanitize(rawHtml, {{ALLOWED_TAGS: DOMPurify.Config, ADD_TAGS: ['use']}})
    : rawHtml;

  // Breadcrumb
  const crumb = page.section !== 'overview'
    ? `<div class="breadcrumb"><span onclick="navigate('index')">Home</span> › ${{page.section}} › ${{page.title}}</div>`
    : '';

  el.innerHTML = `${{crumb}}<div class="md">${{safeHtml}}</div>`;

  // Render mermaid blocks
  await renderMermaid(el);

  // Scroll to top
  el.scrollTop = 0;
}}

async function renderMermaid(container) {{
  const codeBlocks = container.querySelectorAll('code.language-mermaid, pre code');
  const mermaidBlocks = [];

  codeBlocks.forEach(block => {{
    const text = block.textContent || '';
    const isMermaid = block.classList.contains('language-mermaid') ||
      /^(graph|sequenceDiagram|erDiagram|flowchart|classDiagram|gantt|pie|gitGraph)/m.test(text);
    if (isMermaid) mermaidBlocks.push(block);
  }});

  for (let i = 0; i < mermaidBlocks.length; i++) {{
    const block = mermaidBlocks[i];
    const code = block.textContent;
    const id = 'mermaid-' + Date.now() + '-' + i;
    const wrap = document.createElement('div');
    wrap.className = 'mermaid-wrap';
    try {{
      const {{svg}} = await mermaid.render(id, code);
      wrap.innerHTML = svg;
    }} catch (e) {{
      wrap.innerHTML = `<pre style="color:var(--danger);font-size:12px">Diagram error: ${{e.message}}\n${{code}}</pre>`;
    }}
    const pre = block.closest('pre') || block;
    pre.replaceWith(wrap);
  }}
}}

// ---- Search ----
const searchInput = document.getElementById('search');
const searchResults = document.getElementById('searchResults');

searchInput.addEventListener('input', () => {{
  const q = searchInput.value.trim().toLowerCase();
  if (!q) {{ searchResults.classList.remove('open'); return; }}

  const hits = [];
  PAGES.forEach(p => {{
    const inTitle = p.title.toLowerCase().includes(q);
    const inContent = p.content.toLowerCase().includes(q);
    if (inTitle || inContent) {{
      let excerpt = '';
      if (inContent) {{
        const idx = p.content.toLowerCase().indexOf(q);
        excerpt = p.content.slice(Math.max(0, idx - 40), idx + 80).replace(/[#*`]/g, '').trim();
      }}
      hits.push({{...p, excerpt, score: inTitle ? 2 : 1}});
    }}
  }});

  hits.sort((a, b) => b.score - a.score);
  const top = hits.slice(0, 8);

  if (top.length === 0) {{
    searchResults.innerHTML = '<div class="search-result-item" style="color:var(--text3)">No results</div>';
  }} else {{
    searchResults.innerHTML = top.map(h =>
      `<div class="search-result-item" onclick="navigate('${{h.id}}');searchInput.value='';searchResults.classList.remove('open')">
        <div class="search-result-title">${{h.title}}</div>
        <div class="search-result-excerpt">${{h.excerpt}}</div>
      </div>`
    ).join('');
  }}
  searchResults.classList.add('open');
}});

document.addEventListener('click', (e) => {{
  if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {{
    searchResults.classList.remove('open');
  }}
}});

// ---- Init ----
renderSidebar();
renderCurrentPage();
</script>
</body>
</html>"""
