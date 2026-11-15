"""Local content dashboard for the site.

    python admin/server.py          (opens http://127.0.0.1:8790 in your browser)

Runs only on this computer (bound to 127.0.0.1). It edits _pages/ and content/posts/,
moves items into the private Vault folder (../personal-archive/vault-content/, outside the repo),
rebuilds the site, re-encrypts the Vault, and commits + pushes to GitHub.
Every change request must carry the session token printed in the page, so other
websites open in your browser can't drive it.
"""
import json, os, re, secrets, shutil, subprocess, sys, threading, webbrowser, datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote

SITE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE))
import build  # noqa: E402

PORT = int(os.environ.get("ADMIN_PORT", "8790"))
TOKEN = secrets.token_urlsafe(24)
PAGES = SITE / "_pages"                      # public pages
PRIVATE = build.PRIVATE                      # outside the repo
PRIVATE_PAGES = PRIVATE / "_pages"
POSTS = PRIVATE / "content" / "posts"        # new posts live outside the repo (Ideas is a private page)
POST_DIRS = [POSTS, SITE / "content" / "posts"]
VAULT_CONTENT = SITE.parent / "personal-archive" / "vault-content"
PROTECTED_PAGES = {"about", "vault"}
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".json": "application/json",
        ".woff2": "font/woff2", ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
        ".bin": "application/octet-stream", ".md": "text/plain; charset=utf-8"}


def git_exe():
    return shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"


def run(args, env=None):
    p = subprocess.run(args, cwd=SITE, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr).strip()


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "untitled"


def safe_slug(s):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,80}", s or ""):
        raise ValueError("bad slug")
    return s


# ---------- posts ----------
def post_path(slug):
    for d in POST_DIRS:
        for ext in (".html", ".md"):
            p = d / (safe_slug(slug) + ext)
            if p.exists():
                return p
    return None


def write_post(d):
    title = d["title"].strip()
    if not title:
        raise ValueError("Title is required")
    date = d.get("date") or datetime.date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", date):
        raise ValueError("Date must be YYYY-MM")
    topic = slugify(d.get("topic") or "ideas")
    status = d.get("status") if d.get("status") in ("public", "draft") else "draft"
    fmt = "md" if d.get("format") == "md" else "html"
    old = post_path(d["slug"]) if d.get("slug") else None
    slug = d["slug"] if old else slugify(d.get("newSlug") or title)
    if not old:
        base, n = slug, 2
        while post_path(slug):
            slug = f"{base}-{n}"; n += 1
    head = f"<!--\ntitle: {title}\ndate: {date}\ntopic: {topic}\nstatus: {status}\n-->\n"
    folder = old.parent if old else POSTS
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.{fmt}"
    if old and old != path:
        old.unlink()
    path.write_text(head + d.get("body", "").strip() + "\n", encoding="utf-8", newline="\n")
    return slug


def move_to_vault(path, kind):
    VAULT_CONTENT.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8-sig")
    if kind == "page":  # turn the one-line page header into the block header the vault script reads
        meta, body = build.read_page(path)
        text = f"<!--\ntitle: {meta['title']}\ndate: {datetime.date.today():%Y-%m}\ntopic: page\nstatus: vault\n-->\n" + body
    else:
        text = re.sub(r"status:\s*\w+", "status: vault", text, count=1)
    dest = VAULT_CONTENT / f"{kind}-{path.stem}{path.suffix}"
    n = 2
    while dest.exists():
        dest = VAULT_CONTENT / f"{kind}-{path.stem}-{n}{path.suffix}"; n += 1
    dest.write_text(text, encoding="utf-8", newline="\n")
    path.unlink()
    return dest.name


# ---------- pages ----------
def page_path(slug):
    for d in (PAGES, PRIVATE_PAGES):
        p = d / f"{safe_slug(slug)}.html"
        if p.exists():
            return p
    return None


def write_page(d, new=False):
    slug = safe_slug(d["slug"]) if not new else slugify(d.get("slug") or d["title"])
    old = page_path(slug)
    if new and old:
        raise ValueError("A page with that address already exists")
    status = d.get("status") if d.get("status") in ("public", "unlisted", "draft", "private") else "draft"
    if slug in PROTECTED_PAGES and status == "private":
        raise ValueError("This page must stay public")
    folder = PRIVATE_PAGES if status == "private" else PAGES
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.html"
    meta = {} if new else build.read_page(old)[0]
    meta.pop("path", None)
    meta.update({"title": d["title"].strip() or slug.capitalize(), "slug": slug, "status": status})
    if d.get("desc") is not None:
        meta["desc"] = d["desc"].replace("|", "/").replace("-->", "").strip()
    if slug == "vault":
        meta["status"] = "unlisted"
    order = ["title", "slug", "status", "robots", "desc"]
    keys = order + [k for k in meta if k not in order]
    head = "<!-- " + " | ".join(f"{k}: {meta[k]}" for k in keys if k in meta and meta[k] != "") + " -->\n"
    body = d.get("body") if d.get("body") is not None else build.read_page(old)[1]
    path.write_text(head + body.strip() + "\n", encoding="utf-8", newline="\n")
    if old and old != path:
        old.unlink()
    return slug


# ---------- state ----------
def state():
    pages = []
    for m, b in build.load_pages():
        pages.append({"slug": m["slug"], "title": m["title"], "status": m["status"], "desc": m.get("desc", ""),
                      "body": b, "protected": m["slug"] in PROTECTED_PAGES})
    posts = []
    for m, b in build.load_posts():
        posts.append({"slug": m["slug"], "title": m.get("title", m["slug"]), "date": m.get("date", ""), "topic": m["topic"],
                      "status": m["status"], "format": m["format"], "body": b})
    posts.sort(key=lambda x: x["date"], reverse=True)
    vj = SITE / "vault" / "vault.json"
    vault_time = vj.stat().st_mtime if vj.exists() else None
    watch = [VAULT_CONTENT, PRIVATE_PAGES, POSTS, PRIVATE / "library", SITE.parent / "personal-archive" / "vault-items.json"]
    pending = []
    for w in watch:
        files = [w] if w.is_file() else (list(w.rglob("*")) if w.exists() else [])
        pending += [f.name for f in files if f.is_file() and (vault_time is None or f.stat().st_mtime > vault_time)]
    private_pages = [p["title"] for p in pages if p["status"] == "private"]
    code, out = run([git_exe(), "status", "--short"])
    return {"pages": pages, "posts": posts, "vault": {"titles": private_pages, "pending": pending},
            "git": out if code == 0 else "git unavailable: " + out}


# ---------- http ----------
PAGE_HTML = (Path(__file__).parent / "index.html")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._send(200, PAGE_HTML.read_text(encoding="utf-8").replace("{{TOKEN}}", TOKEN), "text/html; charset=utf-8")
        if path == "/api/state":
            if self.headers.get("X-Admin-Token") != TOKEN:
                return self._send(403, {"error": "bad token"})
            return self._send(200, state())
        if path.startswith("/site/"):  # preview of the built site
            rel = path[len("/site/"):] or "index.html"
            f = (SITE / rel).resolve()
            if f.is_dir():
                f = f / "index.html"
            if SITE not in f.parents or not f.is_file() or ".git" in f.parts:
                return self._send(404, b"not found", "text/plain")
            return self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Admin-Token") != TOKEN:
            return self._send(403, {"error": "forbidden"})
        n = int(self.headers.get("Content-Length") or 0)
        d = json.loads(self.rfile.read(n) or b"{}")
        path = urlparse(self.path).path
        try:
            out = self.route(path, d)
            return self._send(200, out or {"ok": True})
        except Exception as e:  # report to the page
            return self._send(400, {"error": str(e)})

    def route(self, path, d):
        if path == "/api/posts/save":
            return {"slug": write_post(d), "build": self.rebuild()}
        if path == "/api/posts/delete":
            p = post_path(d["slug"]); p and p.unlink(); return {"build": self.rebuild()}
        if path == "/api/posts/vault":
            p = post_path(d["slug"])
            if not p: raise ValueError("No such post")
            return {"moved": move_to_vault(p, "post"), "build": self.rebuild()}
        if path == "/api/bulk":
            topic, action, done = d["topic"], d["action"], 0
            for m, _ in build.load_posts():
                if m["topic"] != topic:
                    continue
                p = post_path(m["slug"])
                if action == "vault":
                    move_to_vault(p, "post")
                elif action == "delete":
                    p.unlink()
                elif action in ("public", "draft"):
                    t = p.read_text(encoding="utf-8-sig")
                    p.write_text(re.sub(r"status:\s*\w+", "status: " + action, t, count=1), encoding="utf-8", newline="\n")
                done += 1
            return {"count": done, "build": self.rebuild()}
        if path == "/api/pages/save":
            return {"slug": write_page(d), "build": self.rebuild()}
        if path == "/api/pages/new":
            d.setdefault("body", '<div class="article">\n<p>Write here.</p>\n</div>')
            d.setdefault("status", "draft")
            return {"slug": write_page(d, new=True), "build": self.rebuild()}
        if path in ("/api/pages/vault", "/api/pages/delete"):
            if d["slug"] in PROTECTED_PAGES: raise ValueError("This page can't be removed")
            p = page_path(d["slug"])
            if not p: raise ValueError("No such page")
            if path.endswith("vault"):
                return {"moved": move_to_vault(p, "page"), "build": self.rebuild()}
            p.unlink(); return {"build": self.rebuild()}
        if path == "/api/build":
            return {"build": self.rebuild()}
        if path == "/api/vault/encrypt":
            pw = d.get("password", "")
            env = dict(os.environ, VAULT_PASSPHRASE=pw)
            code, out = run([sys.executable, "tools/vault_encrypt.py"], env=env)
            if code: raise ValueError(out.splitlines()[-1] if out else "Encryption failed")
            return {"output": out.splitlines()[-1]}
        if path == "/api/publish":
            msg = (d.get("message") or "Update site").strip()[:200]
            log = [self.rebuild()]
            if d.get("password"):
                code, out = run([sys.executable, "tools/vault_encrypt.py"], env=dict(os.environ, VAULT_PASSPHRASE=d["password"]))
                if code:
                    raise ValueError(out.splitlines()[-1] if out else "Encryption failed")
                log.append(out.splitlines()[-1])
            g = git_exe()
            for args in ([g, "add", "-A"], [g, "commit", "-m", msg], [g, "push", "origin", "main"]):
                code, out = run(args)
                log.append("$ git " + " ".join(args[1:3]) + "\n" + out)
                if code and not (args[1] == "commit" and "nothing to commit" in out):
                    raise ValueError("\n".join(log))
            return {"output": "\n".join(log)}
        raise ValueError("Unknown action")

    def rebuild(self):
        code, out = run([sys.executable, "build.py"])
        if code:
            raise ValueError("Build failed:\n" + out)
        return out.splitlines()[-1] if out else ""


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}/"
    print("Content dashboard running at", url, "(Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
