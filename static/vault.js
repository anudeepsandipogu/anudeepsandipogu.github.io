/* Vault: password popup, in-browser decryption, and the private-page viewer.
   Files in vault/ are AES-256-GCM ciphertext. The key is derived from the password
   (PBKDF2-SHA256, 600k rounds), kept only in this tab's sessionStorage, and cleared
   on "Lock vault", after 15 idle minutes, or when the tab closes. */
(function () {
  var KEY = "vault-key", IDLE = 15 * 60 * 1000, enc = new TextEncoder();
  var cache = { key: null, man: null, index: null }, idleTimer = null;

  function b64d(s) { var b = atob(s), u = new Uint8Array(b.length); for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; }
  function b64e(buf) { var u = new Uint8Array(buf), s = ""; for (var i = 0; i < u.length; i++) s += String.fromCharCode(u[i]); return btoa(s); }
  function store(raw) { try { if (raw) sessionStorage.setItem(KEY, raw); else sessionStorage.removeItem(KEY); } catch (e) {} }
  function stored() { try { return sessionStorage.getItem(KEY); } catch (e) { return null; } }

  async function manifest() {
    if (!cache.man) { var r = await fetch("vault/vault.json", { cache: "no-store" }); if (!r.ok) throw new Error("empty"); cache.man = await r.json(); }
    return cache.man;
  }
  async function decryptBytes(key, u, aad) {
    return crypto.subtle.decrypt({ name: "AES-GCM", iv: u.slice(0, 12), additionalData: enc.encode(aad) }, key, u.slice(12));
  }
  async function unlock(pw) {
    var m = await manifest();
    var base = await crypto.subtle.importKey("raw", enc.encode(pw), "PBKDF2", false, ["deriveKey"]);
    var key = await crypto.subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt: b64d(m.salt), iterations: m.iter },
      base, { name: "AES-GCM", length: 256 }, true, ["decrypt"]);
    await decryptBytes(key, b64d(m.check), "check"); // throws on a wrong password
    store(b64e(await crypto.subtle.exportKey("raw", key)));
    cache.key = key; touch(); sync();
    return key;
  }
  async function key() {
    if (cache.key) return cache.key;
    var raw = stored(); if (!raw) return null;
    cache.key = await crypto.subtle.importKey("raw", b64d(raw), "AES-GCM", false, ["decrypt"]);
    return cache.key;
  }
  function lock() {
    store(null); cache.key = null; cache.index = null; clearTimeout(idleTimer); sync();
    if (document.getElementById("vaultView")) location.href = "index.html";
  }
  function touch() { clearTimeout(idleTimer); if (stored()) idleTimer = setTimeout(lock, IDLE); }
  function sync() { var b = document.getElementById("lockBtn"); if (b) b.hidden = !stored(); }

  async function item(id) {
    var k = await key(); if (!k) throw new Error("locked");
    var r = await fetch("vault/" + id + ".bin", { cache: "no-store" }); if (!r.ok) throw new Error("missing file");
    return decryptBytes(k, new Uint8Array(await r.arrayBuffer()), id);
  }
  async function index() {
    if (cache.index) return cache.index;
    var m = await manifest(), k = await key(); if (!k) throw new Error("locked");
    var r = await fetch("vault/" + m.index, { cache: "no-store" });
    cache.index = JSON.parse(new TextDecoder().decode(await decryptBytes(k, new Uint8Array(await r.arrayBuffer()), "index")));
    return cache.index;
  }

  /* ---- password popup ---- */
  var dlg = null;
  function ask() {
    return new Promise(function (resolve, reject) {
      if (!dlg) {
        dlg = document.createElement("dialog");
        dlg.className = "vault-dlg";
        dlg.innerHTML = '<form method="dialog" autocomplete="off"><label class="kicker" for="vaultPw">Vault password</label>' +
          '<input id="vaultPw" type="password" autocomplete="off" spellcheck="false" required>' +
          '<span class="note" id="vaultMsg" role="status" aria-live="polite"></span>' +
          '<div class="vault-actions"><button class="toggle" type="button" id="vaultCancel">Cancel</button>' +
          '<button class="toggle primary" type="submit">Unlock</button></div></form>';
        document.body.appendChild(dlg);
      }
      var form = dlg.querySelector("form"), pw = dlg.querySelector("#vaultPw"), msg = dlg.querySelector("#vaultMsg");
      msg.textContent = ""; pw.value = "";
      dlg.querySelector("#vaultCancel").onclick = function () { dlg.close(); reject(new Error("cancelled")); };
      form.onsubmit = async function (e) {
        e.preventDefault(); msg.textContent = "Checking…";
        try { var k = await unlock(pw.value); pw.value = ""; dlg.close(); resolve(k); }
        catch (err) { msg.textContent = err.message === "empty" ? "The vault is empty." : "Wrong password."; pw.select(); }
      };
      dlg.oncancel = function () { reject(new Error("cancelled")); };
      dlg.showModal(); pw.focus();
    });
  }
  async function ensure() { return (await key()) || ask(); }

  /* ---- viewer for library files (decks, wikis, PDFs) ---- */
  function libEntry(ix, path) {
    path = path.replace(/^\.\//, "");
    return ix.lib[path] ? [path, ix.lib[path]] : ix.lib[path.replace(/\/?$/, "/") + "index.html"] ?
      [path.replace(/\/?$/, "/") + "index.html", ix.lib[path.replace(/\/?$/, "/") + "index.html"]] : null;
  }
  async function openLib(path, win) {
    var ix = await index(), hit = libEntry(ix, path);
    if (!hit) { if (win) win.close(); alert("That file isn't in the vault."); return; }
    var data = await item(hit[1].id);
    if (hit[1].type !== "text/html") {
      var url = URL.createObjectURL(new Blob([data], { type: hit[1].type }));
      if (win) win.location = url; else window.open(url, "_blank");
      setTimeout(function () { URL.revokeObjectURL(url); }, 120000); return;
    }
    if (win) win.close();
    showFrame(hit[0], new TextDecoder().decode(data));
  }
  function showFrame(path, html) {
    var ov = document.getElementById("vaultFrame");
    if (!ov) {
      ov = document.createElement("div"); ov.id = "vaultFrame"; ov.className = "vault-frame";
      ov.innerHTML = '<div class="vault-frame-bar"><span class="mono" id="vaultFramePath"></span>' +
        '<button class="toggle" type="button" id="vaultFrameClose">Close</button></div><iframe title="Vault file"></iframe>';
      document.body.appendChild(ov);
      ov.querySelector("#vaultFrameClose").onclick = function () { ov.hidden = true; ov.querySelector("iframe").srcdoc = ""; document.body.style.overflow = ""; };
    }
    var fr = ov.querySelector("iframe");
    ov.querySelector("#vaultFramePath").textContent = path.replace(/^library\//, "");
    fr.onload = function () {
      var d = fr.contentDocument; if (!d) return;
      d.addEventListener("click", function (e) {
        var a = e.target.closest && e.target.closest("a[href]"); if (!a) return;
        var href = a.getAttribute("href");
        if (/^(https?:|mailto:)/.test(href)) { e.preventDefault(); window.open(href, "_blank", "noopener"); return; }
        if (href.charAt(0) === "#") return;
        var rel = new URL(href, "https://v/" + path).pathname.slice(1);
        e.preventDefault();
        var page = rel.match(/^([a-z0-9-]+)\.html$/);
        if (page) { ov.hidden = true; document.body.style.overflow = ""; location.href = "vault.html#" + page[1]; return; }
        openLib(rel);
      });
    };
    fr.srcdoc = html; ov.hidden = false; document.body.style.overflow = "hidden";
  }

  /* ---- the vault page itself: list + private pages ---- */
  async function route() {
    var view = document.getElementById("vaultView"); if (!view) return;
    try { await ensure(); } catch (e) { view.innerHTML = '<p>Locked.</p><p><button class="toggle" type="button" id="vaultRetry">Enter password</button></p>';
      document.getElementById("vaultRetry").onclick = route; return; }
    var ix = await index(), h = decodeURIComponent(location.hash.slice(1)), slug = h.split("/")[0], anchor = h.split("/")[1];
    document.querySelectorAll(".nav a").forEach(function (a) { a.toggleAttribute("aria-current", a.dataset.private === (slug || "files")); });
    var page = ix.pages.filter(function (p) { return p.slug === slug; })[0];
    if (page) {
      view.innerHTML = new TextDecoder().decode(await item(page.id));
      document.title = page.title + " · Anudeep Sandipogu";
      var t = anchor && document.getElementById(anchor);
      if (t) t.scrollIntoView(); else window.scrollTo(0, 0);
      return;
    }
    document.title = "Vault · Anudeep Sandipogu";
    var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
    view.innerHTML = '<div class="article"><p>Private pages and files. Only you can open these.</p><h3>Pages</h3><ul class="index-list">' +
      ix.pages.map(function (p) { return '<li><a href="vault.html#' + esc(p.slug) + '">' + esc(p.title) + '</a><span></span></li>'; }).join("") +
      '</ul><h3>Files</h3><ul class="index-list">' +
      ix.files.map(function (f, i) { return '<li><a href="#" data-file="' + i + '">' + esc(f.title) + '</a><span>' + (f.type === "application/pdf" ? "PDF" : "Page") + '</span></li>'; }).join("") +
      "</ul></div>";
    window.scrollTo(0, 0);
  }

  document.addEventListener("click", async function (e) {
    var a = e.target.closest && e.target.closest("a"); if (!a) return;
    if (a.dataset.private && !document.getElementById("vaultView")) { // locked menu item on a public page
      e.preventDefault();
      try { await ensure(); location.href = a.getAttribute("href"); } catch (err) {}
      return;
    }
    var view = document.getElementById("vaultView"); if (!view || !view.contains(a)) return;
    var href = a.getAttribute("href") || "";
    if (a.dataset.file !== undefined) {
      e.preventDefault(); var ix = await index(), f = ix.files[+a.dataset.file];
      var win = f.type === "text/html" ? null : window.open("", "_blank");
      var data = await item(f.id);
      if (f.type === "text/html") showFrame(f.title, new TextDecoder().decode(data));
      else { var url = URL.createObjectURL(new Blob([data], { type: f.type })); win.location = url; }
      return;
    }
    if (href.indexOf("library/") === 0) {
      e.preventDefault();
      var w = /\.(pdf)$/i.test(href) ? window.open("", "_blank") : null;
      openLib(href, w);
    }
  });
  ["click", "keydown", "scroll"].forEach(function (ev) { document.addEventListener(ev, touch, { passive: true }); });
  window.addEventListener("hashchange", route);
  document.addEventListener("DOMContentLoaded", function () {
    sync(); touch();
    var lb = document.getElementById("lockBtn"); if (lb) lb.addEventListener("click", lock);
    route();
  });
  window.Vault = { ensure: ensure, lock: lock, openLib: openLib };
})();
