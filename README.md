# anudeepsandipogu.github.io

Personal site. Geist style, patrickcollison.com structure.

Only About is public. Every other page and file is encrypted; typing the password into the box
under About decrypts them in the browser, adds them to the menu, and opens each at `index.html#slug`.

## Editing

Run the local dashboard:

```
python admin/server.py
```

It opens http://127.0.0.1:8790 (this computer only):

- **Posts**: add, edit, publish, hide, delete, move to the Vault; filter and act by topic. Markdown supported.
- **Pages**: edit text; set Public, Private (under Vault), Unlisted or Draft; add pages.
- **Vault**: re-encrypt private changes.
- **Publish**: rebuild, encrypt private changes (with the password), commit and push.

## Where things live

- Public pages: `_pages/` (this repo).
- Private pages, posts and the files they link to: `../personal-archive/private-site/` (outside this repo, never committed).
- `vault/`: encrypted copies only. `vault.json` holds the salt and a password check; names and paths are inside the encrypted `index.bin`.
- `build.py` builds public pages and renders private ones for encryption; `tools/vault_encrypt.py` encrypts them; `static/vault.js` decrypts in the browser.
- Styles: `static/geist.css`. Fonts: `static/fonts/` (SIL OFL 1.1, Vercel).
