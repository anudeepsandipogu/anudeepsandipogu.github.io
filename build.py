"""Builds the site.

Public pages:  _pages/<slug>.html (in this repo).
Private pages: ../personal-archive/private-site/_pages/<slug>.html (outside the repo).
Posts:         ../personal-archive/private-site/content/posts/ (and content/posts/ here, if any).

Page header (first line):
    <!-- title: Page title | slug: about | status: public | desc: ... -->
  status for public pages: public (in the menu) · unlisted (online, not in the menu) · draft (not built)
  Private pages are hidden until the password is typed into the box under About; then they join
  the menu and open in place at index.html#slug.
Post header:
    <!--
    title: ...
    date: 2026-11
    topic: technology
    status: public        (public · draft)
    -->
  Public posts are inserted, newest first, wherever a page says {{POSTS}}.

Private pages are rendered into ../personal-archive/private-site/build/; tools/vault_encrypt.py
encrypts them (and the private library files) into vault/. Links from public pages to private
pages or library files are turned into plain text, so visitors never hit a password prompt.

Run `python build.py`, or use the dashboard: `python admin/server.py`.
Every top-level .html file is generated; stale ones are removed on each build.
"""
import pathlib, re, datetime, hashlib, html as htmllib, json, os, time

ROOT = pathlib.Path(__file__).resolve().parent
PRIVATE = ROOT.parent / "personal-archive" / "private-site"
NAME = "Anudeep Sandipogu"
EMAIL = "anudeepsanwork@gmail.com"
UPDATED = datetime.date.today().isoformat()
ASSETS = ["geist.css", "site.js", "vault.js"]
# Changes whenever a stylesheet or script changes, so browsers fetch the new copy.
VERSION = hashlib.sha1(b"".join((ROOT / "static" / a).read_bytes() for a in ASSETS if (ROOT / "static" / a).exists())).hexdigest()[:8]

# Old addresses that moved; each gets a tiny redirect page (skipped if a real page takes the name).
REDIRECTS = {"library": "archive", "projects": "work", "reading": "bookshelf", "france": "travel", "vault": "about"}
GATE = """
<form class="gate" id="gate" autocomplete="off">
  <label class="kicker" for="gatePw">Password</label>
  <div class="gate-row"><input id="gatePw" type="password" autocomplete="off" spellcheck="false" required>
  <button class="toggle primary" type="submit">Open</button></div>
  <span class="note" id="gateMsg" role="status" aria-live="polite"></span>
</form>"""
REDIRECT = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Moved</title>'
            '<meta name="robots" content="noindex"><meta http-equiv="refresh" content="0; url={0}">'
            '</head><body><p>Moved to <a href="{0}">{0}</a>.</p></body></html>\n')

SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">{robots}
<link rel="preload" href="static/fonts/Geist-Variable.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="static/geist.css?v={version}">
<script src="static/site.js?v={version}"></script>
<script src="static/vault.js?v={version}" defer></script>
</head>
<body>
<div class="shell">
<aside class="side" id="side">
  <div class="side-top">
    <a class="brand" href="index.html"><b>{name}</b></a>
    <button class="toggle menu-btn" id="menuBtn" type="button" aria-expanded="false" aria-controls="side">Index</button>
  </div>
  <nav class="nav" aria-label="Pages">
{nav}
  </nav>
  <div class="side-foot">
    <button class="toggle" id="themeBtn" type="button" aria-label="Switch colour theme">&#9680; <span id="themeLbl">Dark</span></button>
    <button class="toggle" id="lockBtn" type="button" hidden>Lock</button>
    <a href="mailto:{email}">{email}</a>
    <span>Updated <span class="mono">{updated}</span></span>
  </div>
</aside>
<main class="main" id="main">
<article class="page" id="view">
{body}
</article>
</main>
</div>
</body>
</html>
"""


def write(path, text):
    """Write via a temp file and retry the swap: on Windows another process can hold a file for a moment."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    for attempt in range(10):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            time.sleep(0.2)
    os.replace(tmp, path)


def read_page(path):
    text = path.read_text(encoding="utf-8-sig")
    head, body = text.split("\n", 1)
    meta = dict(kv.split(":", 1) for kv in re.sub(r"^<!--|-->$", "", head.strip()).split("|"))
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    meta.setdefault("status", "public")
    return meta, body


def read_post(path):
    text = path.read_text(encoding="utf-8-sig")
    m = re.match(r"<!--\s*\n(.*?)\n-->\s*\n?", text, re.S)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    else:
        body = text
    meta.setdefault("status", "public")
    meta.setdefault("topic", "ideas")
    meta["slug"] = path.stem
    meta["format"] = path.suffix.lstrip(".")
    meta["path"] = path
    return meta, body


def render_post(meta, body):
    if meta["format"] == "md":
        import markdown
        body = markdown.markdown(body, extensions=["tables"])
    month = datetime.datetime.strptime(meta["date"], "%Y-%m").strftime("%B %Y")
    inner = "\n".join("  " + l for l in body.strip().splitlines())
    return ('<div class="post" id="{slug}" data-topic="{topic}">\n  <div class="date">{month}</div>\n'
            '  <h2>{title}</h2>\n{inner}\n</div>\n').format(slug=meta["slug"], topic=htmllib.escape(meta["topic"]),
                                                       month=month, title=meta["title"], inner=inner)


def page_dirs():
    return [(ROOT / "_pages", False), (PRIVATE / "_pages", True)]


def load_pages():
    out = []
    for d, private in page_dirs():
        for p in sorted(d.glob("*.html")) if d.exists() else []:
            meta, body = read_page(p)
            if private and meta["status"] != "draft":
                meta["status"] = "private"
            meta["path"] = p
            out.append((meta, body))
    return out


def load_posts():
    files = []
    for d in (ROOT / "content" / "posts", PRIVATE / "content" / "posts"):
        if d.exists():
            files += sorted(list(d.glob("*.html")) + list(d.glob("*.md")))
    return [read_post(p) for p in files]


def nav_html(pages, cur):
    """Public pages only. Private pages are added by static/vault.js once the password is in."""
    pub = [m for m, _ in pages if m["status"] == "public"]
    pub.sort(key=lambda m: (m["slug"] != "about", m["title"].lower()))  # About first, then A–Z
    lis = ['      <li><a href="{0}" data-slug="{1}"{2}>{3}</a></li>'.format(
        "index.html" if m["slug"] == "about" else m["slug"] + ".html", m["slug"],
        ' aria-current="page"' if m["slug"] == cur else "", m["title"]) for m in pub]
    return "    <div>\n      <ul>\n" + "\n".join(lis) + "\n      </ul>\n    </div>"


def link_rewriter(private_slugs, in_private):
    """Public pages: unwrap links to private pages and library files.
    Every page: point links at private pages to index.html#slug(/anchor); they open after the password."""
    def fix(m):
        tag, href, text = m.group(0), m.group(1), m.group(2)
        page = re.match(r"(?:\./)?([a-z0-9-]+)\.html(?:#(.+))?$", href)
        is_private_page = bool(page and page.group(1) in private_slugs)
        if not in_private and href.startswith("library/"):
            return text
        if is_private_page:
            target = page.group(1) + ("/" + page.group(2) if page.group(2) else "")
            return tag.replace('href="{0}"'.format(href), 'href="index.html#{0}"'.format(target), 1)
        return tag
    return lambda body: re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', fix, body, flags=re.S)


def main():
    pages = load_pages()
    posts = [(m, b) for m, b in load_posts() if m["status"] == "public"]
    posts.sort(key=lambda mb: mb[0]["date"], reverse=True)
    posts_html = "\n".join(render_post(m, b) for m, b in posts)
    private_slugs = {m["slug"] for m, _ in pages if m["status"] == "private"}
    pub_fix, priv_fix = link_rewriter(private_slugs, False), link_rewriter(private_slugs, True)
    built, private_built = set(), []
    out_dir = PRIVATE / "build"
    for f in out_dir.glob("*.html") if out_dir.exists() else []:
        f.unlink()
    for meta, body in pages:
        if meta["status"] == "draft":
            continue
        slug = meta["slug"]
        body = body.strip().replace("{{EMAIL}}", EMAIL).replace("{{POSTS}}", posts_html)
        if meta["status"] == "private":
            write(out_dir / f"{slug}.html", "<!-- title: {0} -->\n{1}\n".format(meta["title"], priv_fix(body)))
            private_built.append(slug)
            continue
        if slug == "about":
            body += GATE
        title = "{0} · {1}".format(meta["title"], NAME)
        robots = '\n<meta name="robots" content="{0}">'.format(meta["robots"]) if "robots" in meta else ""
        out = SHELL.format(version=VERSION, title=title, desc=meta.get("desc", meta["title"]), robots=robots, name=NAME,
                           nav=nav_html(pages, slug), email=EMAIL, updated=UPDATED, body=pub_fix(body))
        write(ROOT / (slug + ".html"), out)
        built.add(slug)
        if slug == "about":  # the home page is the About page
            write(ROOT / "index.html", out.replace("<title>{0}</title>".format(title), "<title>{0}</title>".format(NAME)))
            built.add("index")
    redirects = dict(REDIRECTS)
    redirects.update({s: s for s in private_slugs})  # old public addresses of pages that are now private
    for old, new in redirects.items():
        if new in private_slugs:
            target = "index.html#" + new
        elif new == "about":
            target = "index.html"
        elif new in built:
            target = new + ".html"
        else:
            continue
        if old not in built:
            write(ROOT / (old + ".html"), REDIRECT.format(target))
            built.add(old)
    for f in ROOT.glob("*.html"):  # remove pages that were unpublished
        if f.stem not in built:
            f.unlink()
            print("removed", f.name)
    print("built", len(built), "public files,", len(private_built), "private pages,", len(posts), "posts")


if __name__ == "__main__":
    main()
