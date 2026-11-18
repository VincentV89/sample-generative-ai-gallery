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

  const state = {
    options: null,
    selection: { era: null, role: null, style: null, likeness: 'balanced' },
    photo: null, // JPEG data URL, centre-cropped to 2:3 in the browser
    displayTimers: [],
  };

  // ---------- photo upload ----------
  const PHOTO_W = 832;
  const PHOTO_H = 1248; // 2:3 portrait, ~1 MP: what the painter is given

  const loadImage = (file) => new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('That file could not be read as an image. Try a JPEG or PNG.')); };
    img.src = url;
  });

  // Centre-crop to 2:3, resize and re-encode as JPEG (also strips EXIF/location metadata).
  const preparePhoto = async (file) => {
    if (!file.type.startsWith('image/') && !/\.(jpe?g|png|webp|heic|heif)$/i.test(file.name)) {
      throw new Error('Please choose an image file.');
    }
    const img = await loadImage(file);
    const sw = img.naturalWidth;
    const sh = img.naturalHeight;
    if (sw < 256 || sh < 256) throw new Error('That photo is too small. Please use one at least 256 px wide.');
    const target = PHOTO_W / PHOTO_H;
    let cw = sw;
    let ch = sh;
    if (sw / sh > target) cw = Math.round(sh * target); else ch = Math.round(sw / target);
    // Keep faces in frame: crop horizontally from the centre, vertically from slightly above centre.
    const cx = Math.round((sw - cw) / 2);
    const cy = Math.round((sh - ch) * 0.35);
    const scale = Math.min(1, PHOTO_W / cw);
    const canvas = el('canvas');
    canvas.width = Math.max(256, Math.round(cw * scale));
    canvas.height = Math.max(384, Math.round(ch * scale));
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, cx, cy, cw, ch, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.88);
  };

  const setPhoto = (dataUrl) => {
    state.photo = dataUrl;
    $('#photo-preview').hidden = !dataUrl;
    $('#photo-remove').hidden = !dataUrl;
    $('#likeness-step').hidden = !dataUrl;
    $('#consent-row').hidden = !dataUrl;
    $('.pipeline li[data-stage="swapping"]').hidden = !dataUrl;
    $('#twist-step').textContent = dataUrl ? '6' : '5';
    if (dataUrl) $('#photo-img').src = dataUrl;
    else $('#photo-img').removeAttribute('src');
    $('#consent').checked = false;
  };

  const onPhotoChosen = async (ev) => {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = '';
    if (!file) return;
    showError('');
    try {
      setPhoto(await preparePhoto(file));
    } catch (err) {
      showError(err.message);
    }
  };

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

  const ORDER = ['queued', 'directing', 'painting', 'swapping', 'done'];
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
    const { era, role, style, likeness } = state.selection;
    if (!era || !role || !style) { showError('Pick an era, a role and an art style (or hit “Surprise me”).'); return; }
    if (state.photo && !$('#consent').checked) { showError('Please tick the photo consent box (or remove your photo).'); return; }
    const button = $('#generate');
    button.disabled = true;
    button.textContent = 'Painting…';
    setStage('progress');
    updatePipeline('queued');
    if (window.matchMedia('(max-width: 960px)').matches) $('#stage').scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
      const { id } = await api('/portraits', {
        method: 'POST',
        body: JSON.stringify({
          era, role, style, idea: $('#idea').value.trim(),
          ...(state.photo ? { photo: state.photo, consent: true, likeness } : {}),
        }),
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

  const portraitInfo = (p, { headingTag = 'h2', withActions = true, withOpenLink = true } = {}) => {
    const palette = el('div', { class: 'palette', 'aria-label': 'Colour palette' },
      (p.palette || []).filter((c) => HEX.test(c)).map((c) => {
        const s = el('span', { title: c });
        s.style.background = c;
        return s;
      }));
    const shareUrl = `${location.origin}${location.pathname}#/p/${p.id}`;
    const actions = withActions ? el('div', { class: 'result-actions' },
      withOpenLink ? el('a', { class: 'btn primary', href: `#/p/${p.id}`, text: 'Open portrait page' }) : null,
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
        [p.eraLabel, p.roleLabel, p.styleLabel, p.fromPhoto ? '📷 From a visitor photo' : null]
          .filter(Boolean).map((t) => el('span', { class: 'tag', text: t }))),
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
    root.replaceChildren(framed(p),
      el('p', { class: 'on-display', text: '✨ Your portrait is now on the gallery display. Look up!' }),
      portraitInfo(p));
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
      root.replaceChildren(el('div', { class: 'detail' }, framed(p), portraitInfo(p, { headingTag: 'h1', withOpenLink: false })));
    } catch (err) {
      root.replaceChildren(el('p', { class: 'error center', text: err.message }));
    }
  };

  // ---------- gallery display (kiosk screen with QR code) ----------
  const SLIDE_MS = 12000;
  const createUrl = () => `${location.origin}${location.pathname}#/create`;

  const renderQr = () => {
    const img = $('#display-qr-img');
    if (typeof window.qrcode !== 'function') { img.closest('aside').hidden = true; return; }
    const qr = window.qrcode(0, 'M');
    qr.addData(createUrl());
    qr.make();
    img.src = qr.createDataURL(8, 2);
  };

  const slide = (p, isNew) => {
    const bg = el('img', { class: 'display-bg', src: p.imageUrl, alt: '' });
    bg.setAttribute('aria-hidden', 'true');
    const caption = el('div', { class: 'display-caption' },
      isNew ? el('span', { class: 'display-new', text: 'New arrival' }) : null,
      el('h1', { text: p.title || 'Untitled' }),
      el('p', { class: 'display-story', text: p.story || p.caption || '' }),
      el('p', { class: 'display-meta', text: [p.eraLabel, p.roleLabel, p.styleLabel].filter(Boolean).join(' · ') }));
    return el('figure', { class: 'display-slide' }, bg,
      el('img', { class: 'display-art', src: p.imageUrl, alt: p.title || 'AI portrait' }), caption);
  };

  const startDisplay = async () => {
    const stage = $('#display-stage');
    const bar = $('#display-progress-bar');
    renderQr();
    const seen = new Set();
    let first = true;
    let i = 0;
    const tick = async () => {
      try {
        galleryCache = null;
        const items = await loadGallery();
        if (!items.length) {
          stage.replaceChildren(el('div', { class: 'display-waiting' },
            el('h1', { text: 'Your portrait could hang here.' }),
            el('p', { text: 'Scan the QR code to upload a selfie and step into history.' })));
          return;
        }
        // Newly finished portraits jump the queue so visitors see theirs straight away.
        const fresh = first ? [] : items.filter((p) => !seen.has(p.id));
        items.forEach((p) => seen.add(p.id));
        first = false;
        let p;
        if (fresh.length) { p = fresh[fresh.length - 1]; i = 0; } else { p = items[i % items.length]; i += 1; }
        const next = slide(p, fresh.length > 0);
        const art = next.querySelector('.display-art');
        await new Promise((resolve) => { art.onload = resolve; art.onerror = resolve; setTimeout(resolve, 4000); });
        const prev = stage.firstElementChild;
        stage.append(next);
        requestAnimationFrame(() => next.classList.add('show'));
        if (prev) setTimeout(() => prev.remove(), 1200);
        bar.classList.remove('run');
        void bar.offsetWidth; // restart the progress animation
        bar.style.animationDuration = `${SLIDE_MS}ms`;
        bar.classList.add('run');
      } catch (err) {
        if (!stage.firstElementChild) stage.replaceChildren(el('p', { class: 'error', text: err.message }));
      }
    };
    await tick();
    state.displayTimers.push(setInterval(tick, SLIDE_MS));
  };

  // ---------- router ----------
  const route = () => {
    state.displayTimers.forEach(clearInterval);
    state.displayTimers = [];
    const hash = location.hash || '#/';
    const [, view, arg] = hash.match(/^#\/([^/]*)\/?(.*)$/) || [];
    const name = { gallery: 'gallery', p: 'portrait', display: 'display', wall: 'display' }[view] || 'studio';
    document.querySelectorAll('.view, .display').forEach((v) => { v.hidden = v.id !== `view-${name}`; });
    document.body.classList.toggle('kiosk', name === 'display');
    document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === name));
    if (name !== 'portrait') document.title = 'Time-Travel Portrait Studio · Generative AI Gallery on Amazon Bedrock';
    if (name === 'gallery') showGallery();
    if (name === 'portrait') showPortrait(arg);
    if (name === 'display') startDisplay();
    window.scrollTo(0, 0);
  };

  const init = async () => {
    window.addEventListener('hashchange', route);
    $('#studio-form').addEventListener('submit', generate);
    $('#surprise').addEventListener('click', surprise);
    $('#gallery-more').addEventListener('click', () => showGallery(true));
    $('#photo-camera').addEventListener('change', onPhotoChosen);
    $('#photo-file').addEventListener('change', onPhotoChosen);
    $('#photo-remove').addEventListener('click', () => setPhoto(null));
    const idea = $('#idea');
    idea.addEventListener('input', () => { $('#idea-count').textContent = idea.value.length; });
    route();
    try {
      state.options = await api('/options');
      renderChips('era-options', 'era', state.options.eras);
      renderChips('role-options', 'role', state.options.roles);
      renderChips('style-options', 'style', state.options.styles);
      renderChips('likeness-options', 'likeness', (state.options.likeness || []).map((l) => ({ ...l, years: l.hint })));
      state.selection.likeness = state.options.defaultLikeness || 'balanced';
      select('likeness', state.selection.likeness);
      idea.maxLength = state.options.maxIdeaLength;
      $('#idea-max').textContent = state.options.maxIdeaLength;
    } catch (err) {
      showError(`Could not load options: ${err.message}`);
    }
  };

  init();
})();
