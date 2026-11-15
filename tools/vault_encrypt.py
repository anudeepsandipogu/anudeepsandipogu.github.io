"""Encrypt everything private into vault/ for the locked part of the site.

    python tools/vault_encrypt.py          (asks for the password)

What gets encrypted (all sources live outside this public repo, in ../personal-archive/):
  - private pages rendered by build.py        private-site/build/*.html
  - the files those pages link to             private-site/library/**
  - standalone private files                  vault-items.json + vault-content/
Nothing readable is published: vault/vault.json holds only the salt and a password check.
Names, titles and paths are inside vault/index.bin, which is encrypted too.

Scheme (matches static/vault.js, which decrypts in the browser with WebCrypto):
  key  = PBKDF2-HMAC-SHA256(password, salt[16], 600,000 iterations) -> 256-bit AES key
  file = iv[12] || AES-256-GCM(key, iv, data, aad=file id)
The salt is kept while the password stays the same, and unchanged items keep their
existing encrypted file, so publishing doesn't rewrite megabytes every time.
A different password re-encrypts everything.
"""
import base64, getpass, hashlib, hmac, json, mimetypes, os, pathlib, re, sys
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO.parent                      # working folder holding artifacts/ and personal-archive/
ARCHIVE = SRC / "personal-archive"
PRIVATE = ARCHIVE / "private-site"
VAULT_CONTENT = ARCHIVE / "vault-content"
OUT = REPO / "vault"
ITER = 600_000
MIN_LEN = 8

PAGE = ("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>{title}</title><style>body{{font-family:Geist,Helvetica,Arial,sans-serif;max-width:44rem;margin:40px auto;padding:0 16px;"
        "line-height:1.6;color:#0a0a0a;background:#fff}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;"
        "padding:6px 10px 6px 0;text-align:left}}h1,h2{{letter-spacing:-.02em}}</style></head><body>{body}</body></html>")


def b64(b):
    return base64.b64encode(b).decode()


def strip_header(text):
    return re.sub(r"^\s*<!--.*?-->\s*", "", text, count=1, flags=re.S)


def header_title(text, fallback):
    m = re.search(r"^\s*<!--(.*?)-->", text, re.S)
    t = re.search(r"title\s*:\s*(.+?)\s*(\||\n|$)", m.group(1)) if m else None
    return t.group(1) if t else fallback


def as_page(title, body_html):
    import html
    return PAGE.format(title=html.escape(title), body=body_html).encode("utf-8")


def render_md(text):
    import markdown
    return markdown.markdown(strip_header(text), extensions=["tables"])


# ---------- collect ----------
def standalone_files():
    """[(name, title, mime, bytes)] for the Files list."""
    out = []
    items = json.loads((ARCHIVE / "vault-items.json").read_text(encoding="utf-8")) if (ARCHIVE / "vault-items.json").exists() else []
    for slug, title, rel, mime in items:
        p = SRC / rel
        data = as_page(title, render_md(p.read_text(encoding="utf-8-sig"))) if p.suffix == ".md" else p.read_bytes()
        out.append(("file:" + slug, title, mime, data))
    for p in sorted(VAULT_CONTENT.glob("*")) if VAULT_CONTENT.exists() else []:
        if p.suffix not in (".html", ".md"):
            continue
        text = p.read_text(encoding="utf-8-sig")
        title = header_title(text, p.stem.replace("-", " ").capitalize())
        body = render_md(text) if p.suffix == ".md" else "<h1>{0}</h1>{1}".format(title, strip_header(text))
        out.append(("content:" + p.name, title, "text/html", as_page(title, body)))
    return out


def private_pages():
    """[(slug, title, bytes)] rendered by build.py."""
    out = []
    d = PRIVATE / "build"
    for p in sorted(d.glob("*.html")) if d.exists() else []:
        text = p.read_text(encoding="utf-8")
        out.append((p.stem, header_title(text, p.stem.capitalize()), strip_header(text).encode("utf-8")))
    return out


def inline_assets(path, text):
    """Library pages that load sibling .css/.js files get them inlined, so they work when opened from the vault."""
    def css(m):
        f = path.parent / m.group(1)
        return "<style>\n" + f.read_text(encoding="utf-8", errors="ignore") + "\n</style>" if f.is_file() else m.group(0)

    def js(m):
        f = path.parent / m.group(1)
        return "<script>\n" + f.read_text(encoding="utf-8", errors="ignore") + "\n</script>" if f.is_file() else m.group(0)
    text = re.sub(r'<link[^>]+rel="stylesheet"[^>]+href="(?!https?:|/)([^"]+\.css)"[^>]*>', css, text)
    text = re.sub(r'<script[^>]+src="(?!https?:|/)([^"]+\.js)"[^>]*>\s*</script>', js, text)
    return text


def library_files():
    """[(path, mime, bytes)] for every file under private-site/library."""
    out = []
    root = PRIVATE / "library"
    for p in sorted(root.rglob("*")) if root.exists() else []:
        if not p.is_file():
            continue
        rel = "library/" + p.relative_to(root).as_posix()
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix == ".html":
            data = inline_assets(p, p.read_text(encoding="utf-8", errors="ignore")).encode("utf-8")
            mime = "text/html"
        else:
            data = p.read_bytes()
        out.append((rel, mime, data))
    return out


# ---------- encrypt ----------
def derive(pw, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode("utf-8"))


def main():
    pw = os.environ.get("VAULT_PASSPHRASE")
    if not pw:
        pw = getpass.getpass("Vault password (hidden): ")
        if getpass.getpass("Repeat password: ") != pw:
            sys.exit("Passwords differ. Nothing written.")
    if len(pw) < MIN_LEN:
        sys.exit(f"Use at least {MIN_LEN} characters. Nothing written.")

    OUT.mkdir(parents=True, exist_ok=True)
    old_index, salt, key = {}, None, None
    vj = OUT / "vault.json"
    if vj.exists():  # reuse the salt (and unchanged files) when the password is the same
        try:
            m = json.loads(vj.read_text(encoding="utf-8"))
            if m.get("v") == 2:
                s = base64.b64decode(m["salt"]); k = derive(pw, s)
                c = base64.b64decode(m["check"])
                AESGCM(k).decrypt(c[:12], c[12:], b"check")
                salt, key = s, k
                ib = (OUT / m["index"]).read_bytes()
                old_index = json.loads(AESGCM(k).decrypt(ib[:12], ib[12:], b"index"))
        except Exception:
            salt, key, old_index = None, None, {}
    if key is None:
        salt = os.urandom(16)
        key = derive(pw, salt)
    aes = AESGCM(key)
    old_h = old_index.get("h", {})

    def fid(name):
        return hmac.new(key, ("id:" + name).encode(), hashlib.sha256).hexdigest()[:24]

    written, kept, used = 0, 0, set()

    def put(name, data):
        nonlocal written, kept
        i = fid(name)
        h = hmac.new(key, data, hashlib.sha256).hexdigest()[:32]
        used.add(i)
        if old_h.get(i) == h and (OUT / f"{i}.bin").exists():
            kept += 1
        else:
            iv = os.urandom(12)
            (OUT / f"{i}.bin").write_bytes(iv + aes.encrypt(iv, data, i.encode()))
            written += 1
        new_h[i] = h
        return i

    new_h = {}
    index = {"v": 2, "pages": [], "files": [], "lib": {}}
    for slug, title, data in private_pages():
        index["pages"].append({"slug": slug, "title": title, "id": put("page:" + slug, data)})
    for name, title, mime, data in standalone_files():
        index["files"].append({"title": title, "type": mime, "id": put(name, data)})
    for rel, mime, data in library_files():
        index["lib"][rel] = {"id": put("lib:" + rel, data), "type": mime}
    index["h"] = new_h

    iv = os.urandom(12)
    (OUT / "index.bin").write_bytes(iv + aes.encrypt(iv, json.dumps(index).encode("utf-8"), b"index"))
    iv = os.urandom(12)
    manifest = {"v": 2, "kdf": "PBKDF2-SHA256", "iter": ITER, "salt": b64(salt),
                "check": b64(iv + aes.encrypt(iv, b"vault-ok", b"check")), "index": "index.bin"}
    vj.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    removed = 0
    for f in OUT.glob("*.bin"):
        if f.stem not in used and f.name != "index.bin":
            f.unlink(); removed += 1
    print(f"Done: {len(index['pages'])} pages, {len(index['files'])} files, {len(index['lib'])} library files "
          f"({written} written, {kept} unchanged, {removed} removed)")


if __name__ == "__main__":
    main()
