/* Password gate. Only About is readable without it. The other pages and files sit in vault/ as
   AES-256-GCM ciphertext; the key comes from the password (PBKDF2-SHA256, 600k rounds) and is kept
   only in this tab's sessionStorage. "Lock", 15 idle minutes, or closing the tab clears it.
   After unlocking, the menu lists every page and each one opens in place at index.html#slug. */
(function () {
  var KEY = "vault-key", IDLE = 15 * 60 * 1000, NAME = "Anudeep Sandipogu", enc = new TextEncoder();
  var cache = { key: null, man: null, index: null }, idleTimer = null, home = null, homeTitle = null;

  function b64d(s) { var b = atob(s), u = new Uint8Array(b.length); for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; }
  function b64e(buf) { var u = new Uint8Array(buf), s = ""; for (var i = 0; i < u.length; i++) s += String.fromCharCode(u[i]); return btoa(s); }
  function store(raw) { try { if (raw) sessionStorage.setItem(KEY, raw); else sessionStorage.removeItem(KEY); } catch (e) {} }
  function stored() { try { return sessionStorage.getItem(KEY); } catch (e) { return null; } }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

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
  function lock() { store(null); cache.key = null; cache.index = null; clearTimeout(idleTimer); location.href = "index.html"; }
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

  /* ---- menu: public links from the page, plus every private page once unlocked ---- */
  var navDone = false;
  function buildNav(ix) {
    if (navDone) return; navDone = true;
    var ul = document.querySelector(".nav ul"); if (!ul) return;
    var links = [].map.call(ul.querySelectorAll("a"), function (a) { return { href: a.getAttribute("href"), slug: a.dataset.slug, title: a.textContent }; });
    ix.pages.forEach(function (p) { links.push({ href: "index.html#" + p.slug, slug: p.slug, title: p.title }); });
    links.sort(function (a, b) { return (a.slug !== "about") - (b.slug !== "about") || a.title.toLowerCase().localeCompare(b.title.toLowerCase()); });
    if (ix.files.length) links.push({ href: "index.html#files", slug: "files", title: "Files" });
    ul.innerHTML = links.map(function (l) { return '<li><a href="' + esc(l.href) + '" data-slug="' + esc(l.slug) + '">' + esc(l.title) + "</a></li>"; }).join("");
  }
  function setCurrent(slug) {
    document.querySelectorAll(".nav a").forEach(function (a) { a.toggleAttribute("aria-current", a.dataset.slug === slug); });
    var side = document.getElementById("side"), menu = document.getElementById("menuBtn");
    if (side && side.classList.contains("open")) { side.classList.remove("open"); if (menu) menu.setAttribute("aria-expanded", "false"); }
  }

  /* ---- viewer for library files (decks, wikis, PDFs) ---- */
  function libEntry(ix, path) {
    path = path.replace(/^\.\//, "");
    var dir = path.replace(/\/?$/, "/") + "index.html";
    return ix.lib[path] ? [path, ix.lib[path]] : ix.lib[dir] ? [dir, ix.lib[dir]] : null;
  }
  async function openLib(path, win) {
    var ix = await index(), hit = libEntry(ix, path);
    if (!hit) { if (win) win.close(); alert("That file isn't here."); return; }
    var data = await item(hit[1].id);
    if (hit[1].type !== "text/html") {
      var url = URL.createObjectURL(new Blob([data], { type: hit[1].type }));
      if (win) win.location = url; else window.open(url, "_blank");
      setTimeout(function () { URL.revokeObjectURL(url); }, 120000); return;
    }
    if (win) win.close();
    showFrame(hit[0], new TextDecoder().decode(data));
  }
  function closeFrame() { var ov = document.getElementById("vaultFrame"); if (ov) { ov.hidden = true; ov.querySelector("iframe").srcdoc = ""; } document.body.style.overflow = ""; }
  function showFrame(path, html) {
    var ov = document.getElementById("vaultFrame");
    if (!ov) {
      ov = document.createElement("div"); ov.id = "vaultFrame"; ov.className = "vault-frame";
      ov.innerHTML = '<div class="vault-frame-bar"><span class="mono" id="vaultFramePath"></span>' +
        '<button class="toggle" type="button" id="vaultFrameClose">Close</button></div><iframe title="File"></iframe>';
      document.body.appendChild(ov);
      ov.querySelector("#vaultFrameClose").onclick = closeFrame;
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
        if (page) { closeFrame(); location.href = "index.html#" + page[1]; return; }
        openLib(rel);
      });
    };
    fr.srcdoc = html; ov.hidden = false; document.body.style.overflow = "hidden";
  }

  /* ---- what the main column shows ---- */
  function showHome(unlocked) {
    var v = document.getElementById("view");
    if (v.innerHTML !== home) v.innerHTML = home;
    var g = document.getElementById("gate"); if (g) g.hidden = !!unlocked;
    document.title = homeTitle; setCurrent("about");
  }
  async function route() {
    var v = document.getElementById("view"); if (!v) return;
    if (home === null) { home = v.innerHTML; homeTitle = document.title; }
    var h = decodeURIComponent(location.hash.slice(1)), slug = h.split("/")[0], anchor = h.split("/")[1];
    var k = await key();
    if (!k) {
      showHome(false);
      if (slug) { // a link to a private page: ask for the password right here
        var msg = document.getElementById("gateMsg"), pw = document.getElementById("gatePw");
        if (msg) msg.textContent = "Type the password to open that page.";
        if (pw) { pw.scrollIntoView({ block: "center" }); pw.focus(); }
      }
      return;
    }
    var ix = await index(); buildNav(ix);
    var page = ix.pages.filter(function (p) { return p.slug === slug; })[0];
    if (page) {
      v.innerHTML = new TextDecoder().decode(await item(page.id));
      document.title = page.title + " · " + NAME; setCurrent(slug);
      var t = anchor && document.getElementById(anchor);
      if (t) t.scrollIntoView(); else window.scrollTo(0, 0);
      return;
    }
    if (slug === "files") {
      v.innerHTML = '<div class="article"><p>Files: decks, notes and documents.</p><ul class="index-list">' +
        ix.files.map(function (f, i) { return '<li><a href="#" data-file="' + i + '">' + esc(f.title) + '</a><span>' + (f.type === "application/pdf" ? "PDF" : "Page") + "</span></li>"; }).join("") +
        "</ul></div>";
      document.title = "Files · " + NAME; setCurrent("files"); window.scrollTo(0, 0);
      return;
    }
    showHome(true);
    var a2 = slug && document.getElementById(slug); if (a2) a2.scrollIntoView(); else window.scrollTo(0, 0);
  }

  document.addEventListener("submit", async function (e) {
    if (e.target.id !== "gate") return;
    e.preventDefault();
    var pw = document.getElementById("gatePw"), msg = document.getElementById("gateMsg");
    msg.textContent = "Checking…";
    try { await unlock(pw.value); pw.value = ""; msg.textContent = ""; await route(); }
    catch (err) { msg.textContent = err.message === "empty" ? "Nothing is locked yet." : "Wrong password."; pw.select(); }
  });

  document.addEventListener("click", async function (e) {
    var a = e.target.closest && e.target.closest("a"); if (!a) return;
    var view = document.getElementById("view"); if (!view || !view.contains(a)) return;
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
      openLib(href, /\.pdf$/i.test(href) ? window.open("", "_blank") : null);
      return;
    }
    if (href.charAt(0) === "#" && href.length > 1) { // a jump within the open page
      var t = document.getElementById(decodeURIComponent(href.slice(1)));
      if (t) { e.preventDefault(); t.scrollIntoView(); }
    }
  });
  ["click", "keydown", "scroll"].forEach(function (ev) { document.addEventListener(ev, touch, { passive: true }); });
  window.addEventListener("hashchange", route);
  document.addEventListener("DOMContentLoaded", function () {
    sync(); touch();
    var lb = document.getElementById("lockBtn"); if (lb) lb.addEventListener("click", lock);
    route();
  });
  window.Vault = { lock: lock, openLib: openLib };
})();
