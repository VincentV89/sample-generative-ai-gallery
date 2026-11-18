'use strict';

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, props = {}, ...children) => {
    const node = document.createElement(tag);
    Object.entries(props).forEach(([k, v]) => {
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k.startsWith('data-') || k.startsWith('aria-') || k === 'role' || k === 'type') node.setAttribute(k, v);
      else node[k] = v;
    });
    children.flat().filter(Boolean).forEach((c) => node.append(c));
    return node;
  };
  const HEX = /^#[0-9a-fA-F]{6}$/;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const api = async (path, options = {}) => {
    const res = await fetch(`/api${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.message || `Request failed (${res.status})`);
    return body;
  };

  const state = { options: null, selection: { era: null, role: null, style: null }, polling: null, wallTimer: null };

  // ---------- studio ----------
  const renderChips = (containerId, kind, items) => {
    const container = $(`#${containerId}`);
    container.replaceChildren(...items.map((item) => {
      const chip = el('button', {
        type: 'button', class: 'chip', role: 'radio', 'aria-checked': 'false', 'data-id': item.id,
      }, item.emoji ? `${item.emoji} ${item.label}` : item.label, item.years ? el('small', { text: item.years }) : null);
      chip.addEventListener('click', () => select(kind, item.id));
      return chip;
    }));
  };

  const select = (kind, id) => {
    state.selection[kind] = id;
    const container = $(`#${kind}-options`);
    container.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-checked', String(c.dataset.id === id)));
  };

  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
  const surprise = () => {
    const { eras, roles, styles } = state.options;
    select('era', pick(eras).id);
    select('role', pick(roles).id);
    select('style', pick(styles).id);
  };

  const showError = (msg) => {
    const node = $('#form-error');
    node.textContent = msg || '';
    node.hidden = !msg;
  };

  const setStage = (which) => {
    ['empty', 'progress', 'result'].forEach((s) => { $(`#stage-${s}`).hidden = s !== which; });
  };

  const ORDER = ['queued', 'directing', 'painting', 'done'];
  const updatePipeline = (stage, title) => {
    const idx = ORDER.indexOf(stage);
    document.querySelectorAll('.pipeline li').forEach((li) => {
      const i = ORDER.indexOf(li.dataset.stage);
      li.classList.toggle('done', i < idx);
      li.classList.toggle('active', i === idx);
    });
    $('#progress-title').textContent = title ? `“${title}”` : '';
  };

  const generate = async (ev) => {
    ev.preventDefault();
    showError('');
    const { era, role, style } = state.selection;
    if (!era || !role || !style) { showError('Pick an era, a role and an art style (or hit “Surprise me”).'); return; }
    const button = $('#generate');
    button.disabled = true;
    button.textContent = 'Painting…';
    setStage('progress');
    updatePipeline('queued');
    try {
      const { id } = await api('/portraits', {
        method: 'POST',
        body: JSON.stringify({ era, role, style, idea: $('#idea').value.trim() }),
      });
      const portrait = await poll(id);
      renderResult(portrait);
    } catch (err) {
      setStage('empty');
      showError(err.message);
    } finally {
      button.disabled = false;
      button.textContent = 'Paint my portrait';
    }
  };

  const poll = async (id) => {
    const started = Date.now();
    while (Date.now() - started < 4 * 60 * 1000) {
      const p = await api(`/portraits/${id}`);
      updatePipeline(p.stage, p.title);
      if (p.status === 'COMPLETE') return p;
      if (p.status === 'FAILED' || p.status === 'REJECTED') throw new Error(p.error || 'Generation failed.');
      await sleep(2000);
    }
    throw new Error('This is taking longer than expected. Check the gallery in a minute.');
  };

  const portraitInfo = (p, { headingTag = 'h2', withActions = true } = {}) => {
    const palette = el('div', { class: 'palette', 'aria-label': 'Colour palette' },
      (p.palette || []).filter((c) => HEX.test(c)).map((c) => {
        const s = el('span', { title: c });
        s.style.background = c;
        return s;
      }));
    const shareUrl = `${location.origin}${location.pathname}#/p/${p.id}`;
    const actions = withActions ? el('div', { class: 'result-actions' },
      el('a', { class: 'btn primary', href: `#/p/${p.id}`, text: 'Open portrait page' }),
      el('a', { class: 'btn ghost', href: p.imageUrl, download: `${(p.title || 'portrait').replace(/[^\w-]+/g, '-')}.jpg`, text: '⬇ Download' }),
      (() => {
        const b = el('button', { type: 'button', class: 'btn ghost', text: '🔗 Copy link' });
        b.addEventListener('click', async () => {
          try { await navigator.clipboard.writeText(shareUrl); b.textContent = '✓ Copied'; } catch { b.textContent = shareUrl; }
        });
        return b;
      })(),
    ) : null;
    return el('div', { class: 'result' },
      el(headingTag, { text: p.title || 'Untitled' }),
      el('p', { class: 'caption', text: p.caption || '' }),
      el('div', { class: 'tags' },
        [p.eraLabel, p.roleLabel, p.styleLabel].filter(Boolean).map((t) => el('span', { class: 'tag', text: t }))),
      el('p', { class: 'story', text: p.story || '' }),
      palette,
      el('details', {},
        el('summary', { text: 'Behind the canvas: the prompt Claude wrote' }),
        el('p', { text: p.prompt || '' }),
        el('p', { text: `Art director: ${p.textModel || ''} · Painter: ${p.imageModel || ''}` })),
      actions,
    );
  };

  const framed = (p) => el('div', { class: 'frame reveal' }, el('img', { src: p.imageUrl, alt: p.title || 'AI portrait' }));

  const renderResult = (p) => {
    const root = $('#stage-result');
    root.replaceChildren(framed(p), portraitInfo(p));
    setStage('result');
    galleryCache = null; // new item: refresh gallery next time
  };

  // ---------- gallery ----------
  let galleryCache = null;
  let galleryCursor = null;

  const card = (p) => {
    const node = $('#tpl-card').content.firstElementChild.cloneNode(true);
    node.href = `#/p/${p.id}`;
    const img = node.querySelector('img');
    img.src = p.imageUrl;
    img.alt = p.title || 'AI portrait';
    node.querySelector('h3').textContent = p.title || 'Untitled';
    node.querySelector('p').textContent = [p.eraLabel, p.styleLabel].filter(Boolean).join(' · ');
    return node;
  };

  const loadGallery = async (more = false) => {
    if (!more && galleryCache) return galleryCache;
    const page = await api(`/gallery${more && galleryCursor ? `?cursor=${encodeURIComponent(galleryCursor)}` : ''}`);
    galleryCursor = page.cursor;
    galleryCache = more ? [...(galleryCache || []), ...page.items] : page.items;
    return galleryCache;
  };

  const showGallery = async (more = false) => {
    try {
      const items = await loadGallery(more);
      $('#gallery-grid').replaceChildren(...items.map(card));
      $('#gallery-empty').hidden = items.length > 0;
      $('#gallery-more').hidden = !galleryCursor;
    } catch (err) {
      $('#gallery-grid').replaceChildren(el('p', { class: 'error', text: err.message }));
    }
  };

  // ---------- portrait page ----------
  const showPortrait = async (id) => {
    const root = $('#portrait-detail');
    root.replaceChildren(el('p', { class: 'muted center', text: 'Loading portrait…' }));
    try {
      const p = await api(`/portraits/${encodeURIComponent(id)}`);
      if (p.status !== 'COMPLETE') throw new Error('This portrait is still being painted. Try again shortly.');
      document.title = `${p.title} · Time-Travel Portrait Studio`;
      root.replaceChildren(el('div', { class: 'detail' }, framed(p), portraitInfo(p, { headingTag: 'h1' })));
    } catch (err) {
      root.replaceChildren(el('p', { class: 'error center', text: err.message }));
    }
  };

  // ---------- exhibition wall (kiosk) ----------
  const startWall = async () => {
    const root = $('#wall-slide');
    let i = 0;
    const tick = async () => {
      try {
        galleryCache = null;
        const items = await loadGallery();
        if (!items.length) { root.replaceChildren(el('p', { class: 'muted', text: 'Waiting for the first portrait…' })); return; }
        const p = items[i % items.length];
        i += 1;
        root.replaceChildren(framed(p), portraitInfo(p, { headingTag: 'h1', withActions: false }));
      } catch (err) {
        root.replaceChildren(el('p', { class: 'error', text: err.message }));
      }
    };
    await tick();
    state.wallTimer = setInterval(tick, 9000);
  };

  // ---------- router ----------
  const route = () => {
    clearInterval(state.wallTimer);
    const hash = location.hash || '#/';
    const [, view, arg] = hash.match(/^#\/([^/]*)\/?(.*)$/) || [];
    const name = view === 'gallery' ? 'gallery' : view === 'p' ? 'portrait' : view === 'wall' ? 'wall' : 'studio';
    document.querySelectorAll('.view').forEach((v) => { v.hidden = v.id !== `view-${name}`; });
    document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === name));
    if (name !== 'portrait') document.title = 'Time-Travel Portrait Studio · Generative AI Gallery on Amazon Bedrock';
    if (name === 'gallery') showGallery();
    if (name === 'portrait') showPortrait(arg);
    if (name === 'wall') startWall();
    window.scrollTo(0, 0);
  };

  const init = async () => {
    window.addEventListener('hashchange', route);
    $('#studio-form').addEventListener('submit', generate);
    $('#surprise').addEventListener('click', surprise);
    $('#gallery-more').addEventListener('click', () => showGallery(true));
    const idea = $('#idea');
    idea.addEventListener('input', () => { $('#idea-count').textContent = idea.value.length; });
    route();
    try {
      state.options = await api('/options');
      renderChips('era-options', 'era', state.options.eras);
      renderChips('role-options', 'role', state.options.roles);
      renderChips('style-options', 'style', state.options.styles);
      idea.maxLength = state.options.maxIdeaLength;
      $('#idea-max').textContent = state.options.maxIdeaLength;
    } catch (err) {
      showError(`Could not load options: ${err.message}`);
    }
  };

  init();
})();
