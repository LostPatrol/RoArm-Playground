"""Build the course site from tutorial/*.md.

Standard library only. Generates chapter pages, print pages, chapter index,
and optionally print-to-PDF files via a local Chrome/Edge install.
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

# Course source directory and generated static site.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')

# Order, grouping and short blurbs; one row per chapter.
CHAPTERS = [
    ('00-course-map.md', '导览', '导览', '十分钟看清整门课的地形与读法。', 1),
    ('01-what-is-ai.md', '理解', '什么是 AI', '八级台阶：从写死的规则到学出来的能力。', 1),
    ('02-math-model-basics.md', '理解', '数学与模型基础', '十个直觉，不推公式。', 0),
    ('03-neural-networks.md', '理解', '神经网络与训练', '结构怎么进化，能力从哪来。', 0),
    ('04-transformer-and-llm.md', '理解', 'Token、注意力与语言模型', '一句话如何变成一个字的输出。', 1),
    ('05-agent-and-harness.md', '使用', 'Agent 与 Harness', '从聊天到干活，差别在循环与权限。', 1),
    ('06-access-and-cost.md', '使用', '获取模型与成本', '三条路、一笔账、一条安全底线。', 1),
    ('07-talk-to-ai.md', '使用', '和 AI 对话', '把需求说到能被执行。', 1),
    ('08-hallucination-and-verification.md', '使用', '幻觉、遵守与验证', '三种失败，四级验证。', 1),
    ('09-context-memory-and-workflow.md', '使用', '上下文、记忆与工作流', '污染、预算与交接。', 1),
    ('10-multimodal-and-local-models.md', '往外看', '多模态与本地模型', '输入输出图谱、生图路线与量化。', 0),
    ('11-vibecoding-and-people.md', '做出来', 'VibeCoding 实战', '能力地图、交付路径、人是路由器。', 1),
    ('12-robot-project.md', '做出来', '项目案例：机械臂', '一个真实系统的分层、约束与状态表。', 1),
    ('13-teaching-and-assessment.md', '做出来', '教学安排与考核', '四周课表、六个项目与评分。', 0),
    ('appendix-a-glossary.md', '附录', '术语表', '一句话解释，附章节索引。', 0),
    ('appendix-b-resources.md', '附录', '资源索引', '官方入口，只给起点不给结论。', 0),
]

# Existing course grouping; keep teaching labels unchanged.
PARTS = [
    ('导览', '从这里开始'),
    ('理解', '模型是什么，怎么算出来的'),
    ('使用', '拿它做事，并且不被它骗'),
    ('往外看', '文字之外的模型'),
    ('做出来', '交付一个能验收的项目'),
    ('附录', '随手查阅'),
]


# ---------- markdown ----------

def slugify(text):
    """Create an anchor from an existing heading."""
    s = re.sub(r'<[^>]+>', '', text)
    s = re.sub(r'[^\w\u4e00-\u9fff]+', '-', s).strip('-').lower()
    return s or 'section'


def inline(text):
    """Render the supported inline Markdown syntax."""
    text = html.escape(text, quote=False)
    stash = []

    def keep(m):
        """Keep inline code out of subsequent substitutions."""
        stash.append(m.group(1))
        return '\x00%d\x00' % (len(stash) - 1)

    text = re.sub(r'`([^`]+)`', keep, text)
    text = re.sub(r'!\[([^\]]*)\]\(([^)\s]+)\)', r'<img alt="\1" src="\2">', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub('\x00(\\d+)\x00', lambda m: '<code>%s</code>' % stash[int(m.group(1))], text)
    return text


def cells(row):
    """Split a Markdown table row."""
    return [c.strip() for c in row.strip().strip('|').split('|')]


def is_table_sep(line):
    """Identify a Markdown table separator."""
    return bool(re.match(r'^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$', line))


def render_blocks(lines, toc, level_base=0):
    """Render course blocks without rewriting their wording."""
    out = []
    i, n = 0, len(lines)
    para = []

    def flush():
        """Emit the accumulated paragraph."""
        if para:
            out.append('<p>%s</p>' % inline(' '.join(para).strip()))
            del para[:]

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Editorial HTML comments at the top of each source file are notes
        # for maintainers, not content: drop them instead of escaping them.
        if stripped.startswith('<!--'):
            flush()
            while i < n and '-->' not in lines[i]:
                i += 1
            i += 1
            continue

        if not stripped:
            flush()
            i += 1
            continue

        fence = re.match(r'^\s*```(\w*)\s*$', line)
        if fence:
            flush()
            lang = fence.group(1)
            i += 1
            buf = []
            while i < n and not re.match(r'^\s*```\s*$', lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = ' class="language-%s"' % lang if lang else ''
            code = html.escape('\n'.join(buf), quote=False)
            out.append('<pre><code%s>%s</code></pre>' % (cls, code))
            continue

        heading = re.match(r'^(#{1,6})\s+(.*)$', line)
        if heading:
            flush()
            lvl = len(heading.group(1))
            text = heading.group(2).strip()
            if lvl == 1:
                level_base = 1
                out.append('<div class="chapter-head"><h1 id="top">%s</h1></div>' % inline(text))
                i += 1
                continue
            hidden = level_base == 0
            sid = slugify(text)
            out.append('<h%d id="%s">%s</h%d>' % (lvl, sid, inline(text), lvl))
            if not hidden and lvl in (2, 3):
                toc.append((lvl, sid, re.sub(r'\*\*|`', '', text)))
            i += 1
            continue

        if re.match(r'^\s*\|.*\|\s*$', line) and i + 1 < n and is_table_sep(lines[i + 1]):
            flush()
            head = cells(line)
            i += 2
            body = []
            while i < n and re.match(r'^\s*\|.*\|\s*$', lines[i]):
                body.append(cells(lines[i]))
                i += 1
            th = ''.join('<th>%s</th>' % inline(c) for c in head)
            rows = []
            for row in body:
                row = (row + [''] * len(head))[:len(head)]
                rows.append('<tr>%s</tr>' % ''.join('<td>%s</td>' % inline(c) for c in row))
            out.append('<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (th, ''.join(rows)))
            continue

        if re.match(r'^\s*>\s?', line):
            flush()
            buf = []
            while i < n and re.match(r'^\s*>\s?', lines[i]):
                buf.append(re.sub(r'^\s*>\s?', '', lines[i]))
                i += 1
            out.append('<blockquote>%s</blockquote>' % render_blocks(buf, [], level_base))
            continue

        if re.match(r'^\s*(-{3,}|\*{3,})\s*$', line):
            flush()
            out.append('<hr>')
            i += 1
            continue

        if re.match(r'^\s*([-*+]|\d+\.)\s+', line):
            flush()
            ordered = bool(re.match(r'^\s*\d+\.\s+', line))
            items = []
            while i < n and re.match(r'^\s*([-*+]|\d+\.)\s+', lines[i]):
                item = re.sub(r'^\s*([-*+]|\d+\.)\s+', '', lines[i])
                i += 1
                while i < n and lines[i].startswith('   ') and lines[i].strip():
                    item += ' ' + lines[i].strip()
                    i += 1
                items.append('<li>%s</li>' % inline(item))
            tag = 'ol' if ordered else 'ul'
            out.append('<%s>%s</%s>' % (tag, ''.join(items), tag))
            continue

        para.append(stripped)
        i += 1

    flush()
    return '\n'.join(out)


def render_chapter(md):
    """Return chapter HTML and its heading index."""
    lines = md.split('\n')
    toc = []
    body = render_blocks(lines, toc)
    return body, toc


# ---------- pages ----------

def nav_html(items, current, up=''):
    """Render navigation relative to the page directory."""
    links = ['<a href="%s" class="brand">AI <span class="dot">·</span> VibeCoding</a>' % (up + 'index.html')]
    nav = ['<a href="%sindex.html">总览</a>' % up, '<a href="%slab.html">实验</a>' % up,
           '<a href="%squiz.html">自测</a>' % up]
    if current:
        nav.append('<a href="%sdownload.html">下载</a>' % up)
    return ('<header class="topbar"><div class="wrap">%s<nav class="nav">%s</nav></div></header>'
            % (''.join(links), ''.join(nav)))


# Heading classes used by the existing table of contents.
TOC_DEPTH = {2: 'depth-2', 3: 'depth-3'}


def page(title, body, extra_head='', body_class=''):
    """Wrap generated content in the existing page shell."""
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<link rel="stylesheet" href="%(css)s">
%(extra)s
</head>
<body class="%(cls)s">
%(body)s
</body>
</html>
""" % {'title': title, 'css': CSS, 'extra': extra_head, 'cls': body_class, 'body': body}


# Generated chapter pages are one level below the assets directory.
CSS = '../assets/style.css'


def build():
    """Regenerate chapters, print pages, sources and download metadata."""
    os.makedirs(os.path.join(SITE, 'chapters'), exist_ok=True)
    os.makedirs(os.path.join(SITE, 'print'), exist_ok=True)
    os.makedirs(os.path.join(SITE, 'source'), exist_ok=True)
    meta = []

    for idx, (fname, part, label, blurb, star) in enumerate(CHAPTERS):
        path = os.path.join(ROOT, fname)
        md = open(path, encoding='utf-8').read()
        shutil.copyfile(path, os.path.join(SITE, 'source', fname))
        slug = fname[:-3]
        body, toc = render_chapter(md)

        # Wrap the exercise section so it reads as a task box on screen.
        body = re.sub(r'(<h2 id="[^"]*">课后题</h2>)', r'<div class="task-box">\1', body)
        if 'class="task-box"' in body:
            body += '\n</div>'

        h1 = re.search(r'^#\s+(.*)$', md, re.M)
        title = re.sub(r'[*`]', '', h1.group(1)) if h1 else label
        before = CHAPTERS[idx - 1] if idx > 0 else None
        after = CHAPTERS[idx + 1] if idx + 1 < len(CHAPTERS) else None

        def link(item, direction):
            """Link to an adjacent chapter in the same directory."""
            if not item:
                return '<span></span>'
            return ('<a href="%s.html"><span class="dir">%s</span>%s</a>'
                    % (item[0][:-3], direction, item[2]))

        toc_html = ''.join(
            '<li class="%s"><a href="#%s">%s</a></li>' % (TOC_DEPTH.get(lvl, ''), sid, html.escape(text))
            for lvl, sid, text in toc)
        content = ('<div class="layout"><aside class="toc"><div class="toc-title">本章</div>'
                   '<ol>%s</ol></aside><article class="prose">%s'
                   '<nav class="chapter-nav">%s%s</nav></article></div>'
                   % (toc_html, body, link(before, '上一篇'), link(after, '下一篇')))

        pdf = os.path.join(SITE, 'download', slug + '.pdf')
        toolbar = ('<div class="chapter-tools no-print">'
                   '<a href="../print/%s.html" target="_blank" rel="noopener">打印版</a>' % slug)
        if os.path.exists(pdf):
            toolbar += '<a href="../download/%s.pdf">下载本章 PDF</a>' % slug
        toolbar += '</div>'
        page_html = page('%s · AI 与 VibeCoding' % title,
                         nav_html(CHAPTERS, True, up='../') + '<div class="wrap">' + toolbar + content + '</div>'
                         + '<footer><div class="wrap"><span>AI + VibeCoding 课程讲义</span>'
                           '<span><a href="../index.html">返回总览</a></span></div></footer>',
                         body_class='chapter')
        open(os.path.join(SITE, 'chapters', slug + '.html'), 'w', encoding='utf-8', newline='\n').write(page_html)

        print_html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>%(title)s</title>
<link rel="stylesheet" href="../assets/print.css"></head><body class="print-page">
<article id="write">%(body)s</article></body></html>""" % {'title': title, 'body': body}
        open(os.path.join(SITE, 'print', slug + '.html'), 'w', encoding='utf-8', newline='\n').write(print_html)

        meta.append({'slug': slug, 'title': title, 'label': label, 'part': part,
                     'blurb': blurb, 'star': star, 'toc': [[l, s, t] for l, s, t in toc],
                     'pdf': os.path.exists(pdf)})
        print('built', slug)

    data = {'chapters': meta, 'parts': PARTS}
    with open(os.path.join(SITE, 'assets', 'chapters.js'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('window.COURSE = ')
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write(';\n')
    print('wrote assets/chapters.js (%d chapters)' % len(meta))


def find_browser():
    """Find an existing Chrome or Edge installation for PDF export."""
    candidates = [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for name in ('chrome', 'google-chrome', 'chromium', 'msedge'):
        found = shutil.which(name)
        if found:
            return found
    return None


def build_pdfs():
    """Export separate chapter PDFs with an isolated browser profile."""
    browser = find_browser()
    if not browser:
        print('no Chrome/Edge found; skip PDF', file=sys.stderr)
        return 1
    out_dir = os.path.join(SITE, 'download')
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(os.path.dirname(ROOT), 'agent', 'codex', 'pdf-render')
    os.makedirs(work, exist_ok=True)
    failed = []
    for fname, *_ in CHAPTERS:
        slug = fname[:-3]
        src = os.path.join(SITE, 'print', slug + '.html')
        dst = os.path.join(out_dir, slug + '.pdf')
        with tempfile.TemporaryDirectory(dir=work, ignore_cleanup_errors=True) as profile:
            # A separate profile avoids forwarding the request to an open browser.
            cmd = [browser, '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
                   '--user-data-dir=' + profile, '--virtual-time-budget=4000',
                   '--print-to-pdf=' + dst, 'file:///' + src.replace('\\', '/')]
            try:
                result = subprocess.run(cmd, check=False, timeout=90,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                size = os.path.getsize(dst) if os.path.exists(dst) else 0
                if result.returncode != 0 or size == 0:
                    failed.append(slug)
                print('pdf', slug, size)
            except subprocess.TimeoutExpired:
                failed.append(slug)
                print('PDF export timed out:', slug, file=sys.stderr)
    if failed:
        print('PDF export failed: ' + ', '.join(failed), file=sys.stderr)
    return int(bool(failed))


def package_site():
    """Package the site, PDFs and Markdown for another machine."""
    archive = os.path.join(SITE, 'download', 'tutorial-offline.zip')
    os.makedirs(os.path.dirname(archive), exist_ok=True)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for folder, dirs, files in os.walk(SITE):
            dirs[:] = [name for name in dirs if not name.startswith('.')]
            for name in files:
                path = os.path.join(folder, name)
                if os.path.abspath(path) != os.path.abspath(archive):
                    output.write(path, os.path.relpath(path, SITE))
    print('packaged', archive)


def main():
    """Build the static site and optional delivery artifacts."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', action='store_true', help='also export PDFs via Chrome')
    ap.add_argument('--package', action='store_true', help='also create the offline ZIP')
    args = ap.parse_args()
    build()
    if args.pdf:
        result = build_pdfs()
        # Refresh links after exporting PDFs for the first time.
        build()
        if result:
            return result
    if args.package:
        package_site()
    return 0


if __name__ == '__main__':
    sys.exit(main())
