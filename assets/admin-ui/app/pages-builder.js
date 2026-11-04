/* Page builder: page list (/admin/page-builder) and the visual editor (/admin/page-builder/edit/<id>).

   The widget catalog comes from the theme manifest the frontend synced (GET /api/admin/page-builder/themes/<theme>);
   settings forms are generated from its field definitions, plus the platform-level "common" fields (style / motion /
   advanced) the backend defines for every section, column and widget.

   The preview is the REAL frontend in an iframe (signed draft token). Editing happens on that live page:
     - hover/click selects a section / column / widget, a toolbar offers move / duplicate / hide / delete,
     - "+" between sections adds a row (pick 1, 2, 3, 4 columns … structure),
     - widgets are dragged from the palette straight into a column on the page (or between rows),
     - dragging the handle between two columns resizes them (per device),
   all through postMessage with the BuilderBridge overlay inside the iframe (see the frontend's BuilderBridge.tsx). */
(function () {
  'use strict';
  const { api, toast, esc, safe, confirm } = Admin;
  const A = '/api/admin/page-builder';
  const uid = (p) => p + '-' + Math.random().toString(36).slice(2, 10);
  const clone = (o) => JSON.parse(JSON.stringify(o === undefined ? null : o));
  const lbl = (l, lang) => (l && typeof l === 'object' ? (l[lang || 'fa'] || l.fa || Object.values(l)[0] || '') : (l || ''));
  const STATUS = {
    published: ['bg-label-success', 'منتشر شده'], draft: ['bg-label-secondary', 'پیش‌نویس'], scheduled: ['bg-label-info', 'زمان‌بندی‌شده'],
  };
  const ROLE_TITLES = { page: 'صفحه‌ها', area: 'هدر و فوتر', template: 'قالب صفحه‌های جزئیات' };
  const PRESETS = [[12], [6, 6], [4, 4, 4], [3, 3, 3, 3], [8, 4], [4, 8], [3, 9], [9, 3], [3, 6, 3], [2, 8, 2], [5, 7], [7, 5], [2, 2, 2, 2, 2, 2], [4, 2, 2, 2, 2]];
  const TABS = [['content', 'محتوا'], ['style', 'استایل'], ['motion', 'حرکت'], ['advanced', 'پیشرفته']];

  function loadScript(src) {
    return new Promise((res, rej) => {
      if (document.querySelector(`script[src="${src}"]`)) return res();
      const s = document.createElement('script');
      s.src = src; s.onload = res; s.onerror = rej;
      document.head.appendChild(s);
    });
  }

  function modal(title, bodyHtml, okText, onOk, size) {
    const el = document.createElement('div');
    el.className = 'modal fade'; el.tabIndex = -1;
    el.innerHTML = `<div class="modal-dialog ${size || 'modal-lg'} modal-dialog-scrollable"><div class="modal-content">
      <div class="modal-header"><h5 class="modal-title">${esc(title)}</h5><button class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">${bodyHtml}</div>
      <div class="modal-footer">${okText ? `<button class="btn btn-primary" id="m-ok">${esc(okText)}</button>` : ''}<button class="btn btn-label-secondary" data-bs-dismiss="modal">بستن</button></div></div></div>`;
    document.body.appendChild(el);
    const m = new bootstrap.Modal(el);
    el.addEventListener('hidden.bs.modal', () => { m.dispose(); el.remove(); });
    if (okText) el.querySelector('#m-ok').onclick = async () => { if ((await onOk(el)) !== false) m.hide(); };
    m.show();
    return { el, hide: () => m.hide() };
  }

  /* ====================================================================== list */
  Admin.pages.page_builder = async function (root) {
    const th = await api.get(A + '/themes');
    if (!th.themes.length) {
      root.innerHTML = Admin.ui.card('صفحه‌ساز', `<div class="card-body"><div class="alert alert-warning mb-0">
        هنوز هیچ قالب فرانتی همگام نشده است. در پروژهٔ فرانت دستور <code dir="ltr">npm run sync:manifest</code> را اجرا کنید
        (کلید <code>FRONTEND_REVALIDATE_SECRET</code> بک‌اند باید با <code>REVALIDATE_SECRET</code> فرانت یکی باشد).</div></div>`);
      return;
    }
    let theme = sessionStorage.getItem('pb-theme');
    if (!th.themes.some((t) => t.theme === theme)) theme = th.themes[0].theme;

    async function render() {
      const rows = await api.get(A + '/pages' + api.qs({ theme }));
      const cur = th.themes.find((t) => t.theme === theme);
      const groups = ['page', 'area', 'template'].map((role) => [role, rows.filter((p) => (p.role || 'page') === role)]).filter(([, l]) => l.length);
      root.innerHTML = Admin.ui.card('صفحه‌ساز', `<div class="card-body">
        <div class="d-flex flex-wrap gap-2 align-items-center mb-4">
          <select class="form-select w-auto" id="pb-theme">${th.themes.map((t) => `<option value="${esc(t.theme)}" ${t.theme === theme ? 'selected' : ''}>${esc(t.name)} (${esc(t.theme)})</option>`).join('')}</select>
          <span class="text-muted small">${cur.widgets} المان · آخرین همگام‌سازی: ${esc(Admin.dt.toJalali(cur.synced_at) || '—')}${cur.version ? ' · نسخه ' + esc(cur.version) : ''}</span>
          <div class="ms-auto d-flex gap-2">
            <label class="btn btn-label-secondary mb-0"><i class="ti ti-upload me-1"></i>درون‌ریزی<input type="file" accept="application/json" id="pb-import" hidden></label>
            <button class="btn btn-primary" id="pb-new"><i class="ti ti-plus me-1"></i>صفحهٔ جدید</button>
          </div>
        </div>
        ${groups.map(([role, list]) => `<h6 class="text-muted mt-3">${ROLE_TITLES[role]}</h6><div class="table-responsive"><table class="table table-hover align-middle">
          <thead><tr><th>عنوان</th><th>نشانی</th><th>وضعیت</th><th>آخرین تغییر</th><th></th></tr></thead>
          <tbody>${list.map((p) => `<tr>
            <td><a href="/admin/page-builder/edit/${p.id}" class="fw-semibold">${esc(lbl(p.title) || p.slug)}</a> ${p.kind === 'system' ? '<span class="badge bg-label-info ms-1">سیستمی</span>' : ''}</td>
            <td dir="ltr" class="text-end"><code>${esc(p.path)}</code></td>
            <td><span class="badge ${STATUS[p.status][0]}">${STATUS[p.status][1]}</span>${p.status === 'scheduled' ? ` <small class="text-muted">${esc(Admin.dt.toJalali(p.publish_at) || '')}</small>` : ''}${p.has_changes ? ' <span class="badge bg-label-warning">تغییر منتشرنشده</span>' : ''}</td>
            <td>${esc(Admin.dt.toJalali(p.updated_at) || '—')}</td>
            <td class="text-end text-nowrap"><a class="btn btn-sm btn-primary" href="/admin/page-builder/edit/${p.id}"><i class="ti ti-edit me-1"></i>ویرایش</a>
              ${p.kind === 'custom' ? `<button class="btn btn-sm btn-label-danger ms-1 pb-del" data-id="${p.id}"><i class="ti ti-trash"></i></button>` : ''}</td></tr>`).join('')}</tbody></table></div>`).join('') || '<p class="text-muted">صفحه‌ای نیست</p>'}</div>`);
      root.querySelector('#pb-theme').onchange = (e) => { theme = e.target.value; sessionStorage.setItem('pb-theme', theme); render(); };
      root.querySelectorAll('.pb-del').forEach((b) => b.onclick = async () => {
        if (!(await confirm('این صفحه برای همیشه حذف می‌شود.'))) return;
        if (await safe(() => api.del(A + '/pages/' + b.dataset.id))) { toast.ok('حذف شد'); render(); }
      });
      root.querySelector('#pb-new').onclick = () => newPageModal(theme, (p) => { location.href = '/admin/page-builder/edit/' + p.id; });
      root.querySelector('#pb-import').onchange = async (e) => {
        const f = e.target.files[0]; e.target.value = '';
        if (!f) return;
        let data; try { data = JSON.parse(await f.text()); } catch (x) { return toast.err('فایل JSON معتبر نیست'); }
        const p = await safe(() => api.post(A + '/pages/import', data));
        if (p) { toast.ok('صفحه درون‌ریزی شد'); location.href = '/admin/page-builder/edit/' + p.id; }
      };
    }
    await render();
  };

  function newPageModal(theme, done) {
    modal('صفحهٔ جدید', `<div class="mb-3"><label class="form-label">عنوان (فارسی)</label><input class="form-control" id="np-title"></div>
      <div class="mb-3"><label class="form-label">نشانی (slug)</label><input class="form-control" dir="ltr" id="np-slug" placeholder="landing/spring-sale">
      <div class="form-text">فقط حروف انگلیسی کوچک، عدد و «-»؛ می‌تواند تا سه بخش با «/» باشد.</div></div>`, 'ایجاد', async (el) => {
      const p = await safe(() => api.post(A + '/pages', { theme, slug: el.querySelector('#np-slug').value, title: { fa: el.querySelector('#np-title').value } }));
      if (!p) return false;
      done(p);
    });
  }

  /* ====================================================================== editor */
  Admin.pages.page_builder_edit = async function (root, params) {
    await loadScript('/assets/admin-ui/vendor/libs/sortablejs/sortable.js');
    const pid = params.pid;
    const page = await api.get(A + '/pages/' + pid);
    const th = await api.get(A + '/themes/' + encodeURIComponent(page.theme));
    const M = th.manifest;
    const CF = th.common_fields;
    const langs = th.languages;
    const W = Object.fromEntries(M.widgets.map((w) => [w.type, w]));
    const pageDef = (M.pages || []).find((p) => p.key === page.slug) || {};
    const S = {
      page, layout: page.layout, sel: null, lang: 'fa', tab: 'content', hist: [JSON.stringify(page.layout)], hi: 0,
      dirty: false, saving: false, previewOrigin: '', device: 'desktop', sortables: [], saveTimer: null, histTimer: null,
      anim: false, insertCol: null, dragging: false, sample: sessionStorage.getItem('pb-sample-' + pid) || '',
    };

    root.innerHTML = `
      <div class="pb-editor">
        <div class="pb-topbar">
          <a href="/admin/page-builder" class="btn btn-icon btn-label-secondary" title="بازگشت"><i class="ti ti-arrow-right"></i></a>
          <div class="pb-title"><strong id="pb-title"></strong> <span class="badge" id="pb-status"></span> <small class="text-muted" id="pb-save"></small></div>
          <div class="ms-auto d-flex align-items-center gap-1 flex-wrap">
            ${pageDef.sample ? `<select class="form-select form-select-sm w-auto" id="pb-sample" title="پیش‌نمایش با کدام رکورد؟"><option value="">نمونهٔ پیش‌نمایش…</option></select>` : ''}
            <button class="btn btn-icon btn-label-secondary" id="pb-undo" title="بازگشت (Ctrl+Z)"><i class="ti ti-arrow-back-up"></i></button>
            <button class="btn btn-icon btn-label-secondary" id="pb-redo" title="تکرار (Ctrl+Y)"><i class="ti ti-arrow-forward-up"></i></button>
            <div class="btn-group" id="pb-devices">
              <button class="btn btn-icon btn-label-primary active" data-d="desktop" title="دسکتاپ"><i class="ti ti-device-desktop"></i></button>
              <button class="btn btn-icon btn-label-primary" data-d="tablet" title="تبلت"><i class="ti ti-device-tablet"></i></button>
              <button class="btn btn-icon btn-label-primary" data-d="mobile" title="موبایل"><i class="ti ti-device-mobile"></i></button></div>
            <button class="btn btn-icon btn-label-secondary" id="pb-anim" title="پخش انیمیشن‌ها در پیش‌نمایش"><i class="ti ti-player-play"></i></button>
            <button class="btn btn-label-secondary" id="pb-settings"><i class="ti ti-settings me-1"></i>تنظیمات صفحه</button>
            <div class="dropdown"><button class="btn btn-icon btn-label-secondary" data-bs-toggle="dropdown"><i class="ti ti-dots-vertical"></i></button>
              <ul class="dropdown-menu"><li><a class="dropdown-item" href="#" id="pb-rev">تاریخچهٔ نسخه‌ها</a></li>
              <li><a class="dropdown-item" href="#" id="pb-export">خروجی JSON</a></li>
              ${page.kind === 'system' ? '<li><a class="dropdown-item text-danger" href="#" id="pb-reset">بازنشانی به طرح پیش‌فرض قالب</a></li>' : ''}
              <li><a class="dropdown-item" href="#" id="pb-unpub">لغو انتشار</a></li></ul></div>
            <a class="btn btn-label-secondary" id="pb-open" target="_blank" rel="noopener"><i class="ti ti-external-link me-1"></i>باز کردن</a>
            <div class="btn-group"><button class="btn btn-primary" id="pb-publish"><i class="ti ti-rocket me-1"></i>انتشار</button>
              ${page.role === 'page' ? '<button class="btn btn-primary dropdown-toggle dropdown-toggle-split" data-bs-toggle="dropdown"></button><ul class="dropdown-menu"><li><a class="dropdown-item" href="#" id="pb-schedule"><i class="ti ti-clock me-1"></i>زمان‌بندی انتشار…</a></li></ul>' : ''}</div>
          </div>
        </div>
        <div class="pb-body">
          <aside class="pb-left">
            <ul class="nav nav-pills nav-fill p-2" id="pb-tabs">
              <li class="nav-item"><button class="nav-link active" data-t="structure">ساختار</button></li>
              <li class="nav-item"><button class="nav-link" data-t="widgets">المان‌ها</button></li>
              <li class="nav-item"><button class="nav-link" data-t="templates">قالب‌ها</button></li></ul>
            <div class="pb-pane" id="pb-pane-structure"></div>
            <div class="pb-pane d-none" id="pb-pane-widgets"></div>
            <div class="pb-pane d-none" id="pb-pane-templates"></div>
          </aside>
          <main class="pb-center"><div class="pb-frame-wrap" id="pb-frame-wrap"><iframe id="pb-frame" title="پیش‌نمایش"></iframe></div></main>
          <aside class="pb-right" id="pb-right"></aside>
        </div>
      </div>`;
    const $ = (s) => root.querySelector(s);
    const frame = () => $('#pb-frame');
    const post = (msg) => { const f = frame(); if (f && f.contentWindow && S.previewOrigin) f.contentWindow.postMessage(msg, S.previewOrigin); };
    // the preview is rendered at the REAL device width and scaled to fit the stage (so breakpoints behave like on a visitor's device)
    const DEVICE_W = { desktop: 1366, tablet: 820, mobile: 390 };
    S.scale = 1;
    function sendScale() { post({ type: 'pb:scale', scale: S.scale }); }
    function fitFrame() {
      const stage = $('.pb-center'); const f = frame(); if (!stage || !f) return;
      const w = DEVICE_W[S.device] || 1366;
      const availW = stage.clientWidth - 16, availH = stage.clientHeight;
      if (availW < 100) return;   // not laid out yet: the ResizeObserver below calls us again
      S.scale = Math.max(0.2, Math.min(1, availW / w));
      const wrap = $('#pb-frame-wrap');
      wrap.style.width = Math.round(w * S.scale) + 'px'; wrap.style.height = availH + 'px';
      f.style.width = w + 'px'; f.style.height = Math.round(availH / S.scale) + 'px';
      f.style.transform = `scale(${S.scale})`; f.style.transformOrigin = 'top left'; sendScale();
    }
    window.addEventListener('resize', fitFrame);
    if (window.ResizeObserver) new ResizeObserver(fitFrame).observe($('.pb-center'));
    // give the stage as much room as possible: collapse the panel's main menu while editing
    try { if (window.Helpers && Helpers.setCollapsed) Helpers.setCollapsed(true, false); else document.documentElement.classList.add('layout-menu-collapsed'); } catch (e) { /* cosmetic */ }

    /* ---------- layout model helpers ---------- */
    function index() {
      const m = new Map();
      const walk = (cols, parent) => cols.forEach((c) => {
        m.set(c.id, { kind: 'column', o: c, parent, list: cols });
        c.widgets.forEach((w) => { m.set(w.id, { kind: 'widget', o: w, parent: c, list: c.widgets }); if (w.columns) walk(w.columns, w); });
      });
      S.layout.sections.forEach((s) => { m.set(s.id, { kind: 'section', o: s, list: S.layout.sections }); walk(s.columns, s); });
      return m;
    }
    const defaultsOf = (fields) => Object.fromEntries((fields || []).filter((f) => f.default !== undefined).map((f) => [f.name, clone(f.default)]));
    const newColumn = (span) => ({ id: uid('c'), span: span || 12, settings: defaultsOf(M.column_fields), common: {}, widgets: [] });
    const newSection = (spans) => ({ id: uid('s'), hidden: false, settings: defaultsOf(M.section_fields), common: {}, columns: (spans || [12]).map(newColumn) });
    function newWidget(type) {
      if (type === 'inner_row') return { id: uid('w'), type, hidden: false, settings: {}, common: {}, columns: [6, 6].map(newColumn) };
      return { id: uid('w'), type, hidden: false, settings: clone((W[type] || {}).defaults || {}), common: {} };
    }
    function freshIds(n) { n.id = uid(String(n.id).split('-')[0] || 'n'); (n.columns || []).forEach(freshIds); (n.widgets || []).forEach(freshIds); return n; }
    function applyStructure(node, spans) {
      const cols = node.columns;
      const next = spans.map((sp, i) => cols[i] ? Object.assign(cols[i], { span: sp }) : newColumn(sp));
      const extra = cols.slice(spans.length);
      if (extra.length) extra.forEach((c) => next[next.length - 1].widgets.push(...c.widgets)); // never lose widgets when columns are removed
      node.columns = next;
    }
    const wLabel = (w) => (w.type === 'inner_row' ? 'ردیف داخلی' : (W[w.type] ? lbl(W[w.type].label) : w.type));
    const devSpanKey = (d) => (d === 'desktop' ? 'span' : d === 'tablet' ? 'span_tablet' : 'span_mobile');

    /* ---------- change tracking: history + autosave ---------- */
    function pushHist() {
      const snap = JSON.stringify(S.layout);
      if (snap === S.hist[S.hi]) return;
      S.hist = S.hist.slice(0, S.hi + 1); S.hist.push(snap); if (S.hist.length > 80) S.hist.shift(); S.hi = S.hist.length - 1; updBtns();
    }
    function changed(opts) {
      opts = opts || {};
      S.dirty = true; $('#pb-save').textContent = 'تغییرات ذخیره نشده…';
      clearTimeout(S.histTimer); S.histTimer = setTimeout(pushHist, opts.now ? 0 : 500);
      if (opts.now) pushHist();
      clearTimeout(S.saveTimer); S.saveTimer = setTimeout(save, opts.now ? 120 : 800);
    }
    async function save() {
      clearTimeout(S.saveTimer);
      if (S.saving) { S.saveTimer = setTimeout(save, 400); return; }
      S.saving = true; $('#pb-save').textContent = 'در حال ذخیره…';
      try {
        const out = await api.put(A + '/pages/' + pid, { layout: S.layout });
        S.page = out; S.dirty = false; $('#pb-save').textContent = 'ذخیره شد';
        if (out.unknown_widgets && out.unknown_widgets.length) toast.warn('المان‌های ناشناخته برای این قالب نگه داشته شدند: ' + out.unknown_widgets.join('، '));
        paintStatus(); post({ type: 'pb:refresh' });
      } catch (e) { $('#pb-save').textContent = 'خطا در ذخیره'; toast.err(e.message); } finally { S.saving = false; }
    }
    async function flush() {
      while (S.saving) await new Promise((r) => setTimeout(r, 100));
      if (S.dirty) await save();
      while (S.saving) await new Promise((r) => setTimeout(r, 100));
    }
    function paintStatus() {
      const [cls, txt] = STATUS[S.page.status] || STATUS.draft;
      $('#pb-status').className = 'badge ' + cls;
      $('#pb-status').textContent = txt + (S.page.status === 'scheduled' ? ' · ' + (Admin.dt.toJalali(S.page.publish_at) || '') : '') + (S.page.has_changes ? ' · تغییر منتشرنشده' : '');
      $('#pb-title').textContent = lbl(S.page.title) || S.page.slug;
      $('#pb-unpub').parentElement.style.display = S.page.status !== 'draft' ? '' : 'none';
    }
    function updBtns() { $('#pb-undo').disabled = S.hi <= 0; $('#pb-redo').disabled = S.hi >= S.hist.length - 1; }
    function jump(d) {
      const n = S.hi + d; if (n < 0 || n >= S.hist.length) return;
      S.hi = n; S.layout = JSON.parse(S.hist[n]); if (S.sel && !index().has(S.sel)) S.sel = null; renderAll(); updBtns();
      S.dirty = true; clearTimeout(S.saveTimer); S.saveTimer = setTimeout(save, 500);
    }

    /* ---------- structure tree (left) ---------- */
    function colsHtml(cols, inner) {
      return `<div class="pb-cols">${cols.map((c) => `
        <div class="pb-col ${S.sel === c.id ? 'sel' : ''}" data-id="${c.id}">
          <div class="pb-row" data-sel="${c.id}"><i class="ti ti-grip-vertical pb-handle pb-handle-c"></i><span class="flex-grow-1">ستون <small class="text-muted">(${c.span}/12)</small></span>
            <button class="btn btn-icon btn-xs text-danger" data-act="del" data-id="${c.id}" title="حذف ستون"><i class="ti ti-x"></i></button></div>
          <div class="pb-widgets" data-col="${c.id}">${c.widgets.map(widgetHtml).join('')}</div></div>`).join('')}</div>`;
    }
    function widgetHtml(w) {
      const known = w.type === 'inner_row' || W[w.type];
      return `<div class="pb-widget ${S.sel === w.id ? 'sel' : ''} ${w.hidden ? 'is-hidden' : ''} ${known ? '' : 'unknown'}" data-id="${w.id}" data-type="${esc(w.type)}">
        <div class="pb-row" data-sel="${w.id}"><i class="ti ti-grip-vertical pb-handle pb-handle-w"></i><i class="ti ${w.type === 'inner_row' ? 'ti-layout-columns' : esc((W[w.type] || {}).icon || 'ti-help')}"></i>
          <span class="flex-grow-1 text-truncate">${esc(wLabel(w))}${known ? '' : ' <small>(ناشناخته)</small>'}</span>
          <button class="btn btn-icon btn-xs" data-act="hide" data-id="${w.id}"><i class="ti ${w.hidden ? 'ti-eye-off' : 'ti-eye'}"></i></button>
          <button class="btn btn-icon btn-xs" data-act="dup" data-id="${w.id}"><i class="ti ti-copy"></i></button>
          <button class="btn btn-icon btn-xs text-danger" data-act="del" data-id="${w.id}"><i class="ti ti-trash"></i></button></div>
        ${w.columns ? colsHtml(w.columns, true) : ''}</div>`;
    }
    function renderTree() {
      S.sortables.forEach((s) => s.destroy()); S.sortables = [];
      const pane = $('#pb-pane-structure');
      pane.innerHTML = `<div class="pb-tree" id="pb-tree">${S.layout.sections.map((s, si) => `
        <div class="pb-section ${S.sel === s.id ? 'sel' : ''} ${s.hidden ? 'is-hidden' : ''}" data-id="${s.id}">
          <div class="pb-row" data-sel="${s.id}"><i class="ti ti-grip-vertical pb-handle pb-handle-s"></i><span class="flex-grow-1">ردیف ${si + 1}</span>
            <button class="btn btn-icon btn-xs" data-act="hide" data-id="${s.id}" title="نمایش/پنهان"><i class="ti ${s.hidden ? 'ti-eye-off' : 'ti-eye'}"></i></button>
            <button class="btn btn-icon btn-xs" data-act="dup" data-id="${s.id}" title="کپی"><i class="ti ti-copy"></i></button>
            <button class="btn btn-icon btn-xs text-danger" data-act="del" data-id="${s.id}" title="حذف"><i class="ti ti-trash"></i></button></div>
          ${colsHtml(s.columns)}</div>`).join('')}
        ${S.layout.sections.length ? '' : '<div class="text-center text-muted py-4">صفحه خالی است</div>'}</div>
        <div class="p-2"><button class="btn btn-label-primary w-100" id="pb-addsec"><i class="ti ti-plus me-1"></i>افزودن ردیف</button></div>`;

      let pend = false;   // onAdd (target list) and onEnd (source list) both fire for one drop
      const sync = () => {
        if (pend) return; pend = true;
        setTimeout(() => { pend = false; S.layout = readTree(); S.sel = S.sel && index().has(S.sel) ? S.sel : null; changed({ now: true }); renderAll(); }, 0);
      };
      const mk = (el, opts) => S.sortables.push(Sortable.create(el, Object.assign({ animation: 150, fallbackOnBody: true, onEnd: sync, onAdd: sync }, opts)));
      mk($('#pb-tree'), { draggable: '.pb-section', handle: '.pb-handle-s', group: 'pb-sec' });
      pane.querySelectorAll('.pb-cols').forEach((el) => mk(el, { draggable: '.pb-col', handle: '.pb-handle-c', group: 'pb-col' }));
      pane.querySelectorAll('.pb-widgets').forEach((el) => mk(el, { draggable: '.pb-widget', handle: '.pb-handle-w', group: 'pb-widget' }));
    }
    function readTree() {
      const old = index();
      const readCols = (colsEl) => [...colsEl.querySelectorAll(':scope > .pb-col')].map((cEl) => {
        const c = old.get(cEl.dataset.id).o;
        const widgets = [...cEl.querySelectorAll(':scope > .pb-widgets > .pb-widget')].map((wEl) => {
          const w = old.get(wEl.dataset.id).o;
          const inner = wEl.querySelector(':scope > .pb-cols');
          return inner ? Object.assign({}, w, { columns: readCols(inner) }) : w;
        });
        return Object.assign({}, c, { widgets });
      });
      return { v: 1, sections: [...$('#pb-tree').querySelectorAll(':scope > .pb-section')].map((sEl) => {
        const s = old.get(sEl.dataset.id).o;
        return Object.assign({}, s, { columns: readCols(sEl.querySelector(':scope > .pb-cols')) });
      }) };
    }

    /* ---------- palette (left, 2nd tab): pointer-drag onto the live page, or click to add ---------- */
    function renderPalette(q) {
      const pane = $('#pb-pane-widgets');
      const cats = {};
      const items = [{ type: 'inner_row', label: 'ردیف داخلی', description: 'یک ردیف ستون‌دار داخل ستون', category: 'ساختار', icon: 'ti-layout-columns' }].concat(M.widgets);
      items.filter((w) => !q || (lbl(w.label) + w.type).toLowerCase().includes(q.toLowerCase())).forEach((w) => (cats[w.category] = cats[w.category] || []).push(w));
      pane.innerHTML = `<div class="p-2"><input class="form-control" id="pb-q" placeholder="جستجوی المان…" value="${esc(q || '')}"></div>
        <div class="px-2 pb-3">${Object.keys(cats).map((c) => `<div class="text-muted small fw-semibold my-2">${esc(c)}</div>
          <div class="pb-palette">${cats[c].map((w) => `<div class="pb-pal" data-type="${esc(w.type)}" title="${esc(lbl(w.description))}"><i class="ti ${esc(w.icon)}"></i><span>${esc(lbl(w.label))}</span></div>`).join('')}</div>`).join('') || '<div class="text-muted p-3">موردی نیست</div>'}</div>
        <div class="px-3 pb-3 small text-muted">المان را روی صفحهٔ زنده در وسط بکشید و داخل یک ستون یا بین دو ردیف رها کنید؛ یا روی آن کلیک کنید تا به ستون انتخاب‌شده اضافه شود.</div>`;
      const qi = pane.querySelector('#pb-q'); qi.oninput = () => { const v = qi.value; renderPalette(v); const n = $('#pb-q'); n.focus(); n.setSelectionRange(v.length, v.length); };
      pane.querySelectorAll('.pb-pal').forEach((el) => el.addEventListener('pointerdown', (e) => startPaletteDrag(e, el.dataset.type, el.innerText.trim())));
    }
    function startPaletteDrag(e, drop, text) {
      if (e.button !== 0) return;
      e.preventDefault();
      const x0 = e.clientX, y0 = e.clientY;
      let ghost = null, shield = null, started = false, inside = false;
      const rect = () => frame().getBoundingClientRect();
      const local = (ev) => ({ x: (ev.clientX - rect().left) / S.scale, y: (ev.clientY - rect().top) / S.scale });
      const isInside = (ev) => { const r = rect(); return ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom; };
      const move = (ev) => {
        if (!started && Math.hypot(ev.clientX - x0, ev.clientY - y0) > 6) {
          started = true; S.dragging = true;
          ghost = document.createElement('div'); ghost.className = 'pb-ghost'; ghost.textContent = text;
          shield = document.createElement('div'); shield.className = 'pb-shield';
          document.body.append(shield, ghost);
        }
        if (!started) return;
        ghost.style.transform = `translate(${ev.clientX + 14}px, ${ev.clientY + 14}px)`;
        const now = isInside(ev);
        if (now) post(Object.assign({ type: 'pb:drag-move' }, local(ev)));
        else if (inside) post({ type: 'pb:drag-leave' });
        inside = now;
      };
      const up = (ev) => {
        document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up);
        if (ghost) ghost.remove(); if (shield) shield.remove(); S.dragging = false;
        if (!started) return addWidgetClick(drop);
        if (isInside(ev)) post(Object.assign({ type: 'pb:drag-drop', drop }, local(ev))); else post({ type: 'pb:drag-leave' });
      };
      document.addEventListener('pointermove', move); document.addEventListener('pointerup', up);
    }
    function addWidgetClick(type) {
      const idx = index(); let col = null;
      const target = S.insertCol && idx.get(S.insertCol) ? S.insertCol : S.sel;
      const sel = target && idx.get(target);
      if (sel) col = sel.kind === 'column' ? sel.o : sel.kind === 'widget' ? sel.parent : sel.o.columns[0];
      if (!col) { if (!S.layout.sections.length) S.layout.sections.push(newSection([12])); const last = S.layout.sections[S.layout.sections.length - 1]; col = last.columns[0]; }
      const w = newWidget(type); col.widgets.push(w); S.sel = w.id; S.insertCol = null; changed({ now: true }); renderAll(); showTab('structure');
    }

    /* ---------- reusable section templates (left, 3rd tab) ---------- */
    async function renderTemplates() {
      const pane = $('#pb-pane-templates');
      pane.innerHTML = '<div class="p-3 text-muted">در حال بارگذاری…</div>';
      const list = await safe(() => api.get(A + '/templates' + api.qs({ theme: S.page.theme }))) || [];
      pane.innerHTML = `<div class="p-2 small text-muted">ردیف‌هایی که با ★ ذخیره کرده‌اید. روی «درج» بزنید تا به انتهای صفحه اضافه شود.</div>
        <ul class="list-group list-group-flush">${list.map((t) => `<li class="list-group-item d-flex align-items-center gap-1"><span class="flex-grow-1 text-truncate">${esc(t.name)}</span>
          <button class="btn btn-sm btn-label-primary" data-tpl-ins="${t.id}">درج</button><button class="btn btn-sm btn-icon text-danger" data-tpl-del="${t.id}"><i class="ti ti-trash"></i></button></li>`).join('') || '<li class="list-group-item text-muted">قالبی ذخیره نشده است</li>'}</ul>`;
      pane.querySelectorAll('[data-tpl-ins]').forEach((b) => b.onclick = () => insertTemplate(+b.dataset.tplIns, S.layout.sections.length));
      pane.querySelectorAll('[data-tpl-del]').forEach((b) => b.onclick = async () => { if (await confirm('قالب حذف شود؟') && await safe(() => api.del(A + '/templates/' + b.dataset.tplDel))) renderTemplates(); });
    }
    async function insertTemplate(tid, at) {
      const t = await safe(() => api.get(A + '/templates/' + tid)); if (!t) return;
      const sec = freshIds(clone(t.section));
      S.layout.sections.splice(at, 0, sec); S.sel = sec.id; changed({ now: true }); renderAll(); showTab('structure');
    }
    function pickTemplate(at) {
      safe(() => api.get(A + '/templates' + api.qs({ theme: S.page.theme }))).then((list) => {
        if (!list) return;
        const m = modal('قالب‌های آماده', `<div class="list-group">${list.map((t) => `<button type="button" class="list-group-item list-group-item-action" data-tid="${t.id}">${esc(t.name)}</button>`).join('') || '<div class="text-muted">هنوز قالبی ذخیره نشده است. روی یک ردیف دکمهٔ ★ را بزنید.</div>'}</div>`);
        m.el.addEventListener('click', (e) => { const b = e.target.closest('[data-tid]'); if (b) { insertTemplate(+b.dataset.tid, at); m.hide(); } });
      });
    }
    function saveAsTemplate(section) {
      modal('ذخیرهٔ ردیف به‌عنوان قالب آماده', '<label class="form-label">نام قالب</label><input class="form-control" id="tpl-name" placeholder="مثلاً: سه کارت ویژگی">', 'ذخیره', async (el) => {
        const name = el.querySelector('#tpl-name').value.trim();
        if (!name) { toast.err('نام الزامی است'); return false; }
        const out = await safe(() => api.post(A + '/templates', { theme: S.page.theme, name, section }));
        if (!out) return false;
        toast.ok('قالب ذخیره شد'); renderTemplates();
      }, 'modal-md');
    }

    /* ---------- row structure picker ---------- */
    function pickStructure(title, onPick) {
      const m = modal(title, `<div class="pb-presets">${PRESETS.map((p) => `<button type="button" class="pb-preset" data-s="${p.join(',')}" title="${p.join(' + ')}">${p.map((n) => `<span style="flex:${n}">${n}</span>`).join('')}</button>`).join('')}</div>
        <div class="input-group mt-3"><span class="input-group-text">ساختار دلخواه</span><input class="form-control" dir="ltr" id="pb-custom" placeholder="مثلاً 3,6,3 (جمع ≤ 12)"><button class="btn btn-primary" id="pb-custom-ok">اعمال</button></div>`, null, null, 'modal-lg');
      const choose = (spans) => { m.hide(); onPick(spans); };
      m.el.addEventListener('click', (e) => { const b = e.target.closest('.pb-preset'); if (b) choose(b.dataset.s.split(',').map(Number)); });
      m.el.querySelector('#pb-custom-ok').onclick = () => {
        const spans = m.el.querySelector('#pb-custom').value.split(/[,+\s]+/).filter(Boolean).map(Number);
        if (!spans.length || spans.length > 12 || spans.some((n) => !Number.isInteger(n) || n < 1 || n > 12) || spans.reduce((a, b) => a + b, 0) > 12) return toast.err('جمع ستون‌ها باید حداکثر ۱۲ باشد');
        const sum = spans.reduce((a, b) => a + b, 0); spans[spans.length - 1] += 12 - sum; choose(spans);
      };
    }
    function addRow(at) {
      pickStructure('ساختار ردیف جدید', (spans) => {
        const s = newSection(spans); S.layout.sections.splice(at, 0, s); S.sel = s.columns[0].id; S.insertCol = s.columns[0].id;
        changed({ now: true }); renderAll(); showTab('widgets');
      });
    }

    /* ---------- settings panel (right) ---------- */
    const entityCache = {};
    async function entityOptions(kind) {
      if (entityCache[kind]) return entityCache[kind];
      const url = { category: '/api/public/categories?include_empty=1', product: '/api/public/products?per_page=100', project: '/api/public/projects?per_page=100', article: '/api/public/articles?per_page=100',
        brand: '/api/public/brands?per_page=100', tag: '/api/public/tags', sector: '/api/public/project-sectors', article_category: '/api/public/article-categories' }[kind];
      try {
        const d = await (await fetch(url)).json();
        const list = d.categories || d.products || d.projects || d.articles || d.brands || d.tags || d.sectors || [];
        entityCache[kind] = list.map((x) => ({ value: x.slug, label: lbl(x.name || x.title || x.label) || x.slug }));
      } catch (e) { entityCache[kind] = []; }
      return entityCache[kind];
    }

    function fieldHtml(f, v, ctx) {
      const id = ctx.id; const L = S.lang;
      const label = `<label class="form-label">${esc(lbl(f.label))}</label>`;
      const help = f.help ? `<div class="form-text">${esc(lbl(f.help))}</div>` : '';
      const val = v === undefined ? f.default : v;
      const tv = f.i18n ? ((val && typeof val === 'object' ? val[L] : (L === 'fa' ? val : '')) || '') : (val || '');
      switch (f.type) {
        case 'text': return `<div class="mb-3">${label}<input class="form-control" data-f="${id}" data-lang="${f.i18n ? L : ''}" value="${esc(tv)}" ${f.i18n && langs.find((l) => l.code === L).direction === 'ltr' ? 'dir="ltr"' : ''}>${help}</div>`;
        case 'textarea': return `<div class="mb-3">${label}<textarea class="form-control" rows="4" data-f="${id}" data-lang="${f.i18n ? L : ''}">${esc(tv)}</textarea>${help}</div>`;
        case 'richtext': return `<div class="mb-3">${label}<div class="btn-group btn-group-sm mb-1" data-rt="${id}"><button type="button" class="btn btn-label-secondary" data-tag="strong"><b>B</b></button><button type="button" class="btn btn-label-secondary" data-tag="em"><i>I</i></button><button type="button" class="btn btn-label-secondary" data-tag="a">لینک</button><button type="button" class="btn btn-label-secondary" data-tag="ul">فهرست</button><button type="button" class="btn btn-label-secondary" data-tag="h3">تیتر</button></div>
          <textarea class="form-control" rows="8" dir="auto" data-f="${id}" data-lang="${f.i18n ? L : ''}">${esc(tv)}</textarea><div class="form-text">HTML ساده (p، strong، em، a، ul، li، h2–h5، blockquote). موارد دیگر خودکار پاک می‌شوند.</div></div>`;
        case 'number': return `<div class="mb-3">${label}<input type="number" class="form-control" data-f="${id}" ${f.min !== undefined ? `min="${f.min}"` : ''} ${f.max !== undefined ? `max="${f.max}"` : ''} ${f.step ? `step="${f.step}"` : ''} value="${esc(val === undefined || val === null ? '' : val)}">${help}</div>`;
        case 'select': return `<div class="mb-3">${label}<select class="form-select" data-f="${id}">${(f.options || []).map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(val === undefined ? '' : val) ? 'selected' : ''}>${esc(lbl(o.label))}</option>`).join('')}</select>${help}</div>`;
        case 'switch': return `<div class="mb-3 form-check form-switch"><input class="form-check-input" type="checkbox" data-f="${id}" ${val ? 'checked' : ''}><label class="form-check-label">${esc(lbl(f.label))}</label>${help}</div>`;
        case 'color': return `<div class="mb-3">${label}<div class="input-group"><input type="color" class="form-control form-control-color" data-fc="${id}" value="${/^#[0-9a-f]{6}$/i.test(val || '') ? val : '#ffffff'}"><input class="form-control" dir="ltr" data-f="${id}" value="${esc(val || '')}" placeholder="#0b4f8a"><button class="btn btn-label-secondary" type="button" data-clear="${id}">پاک</button></div>${help}</div>`;
        case 'image': return `<div class="mb-3">${label}<div class="pb-img">${val ? `<img src="${esc(val)}" alt="">` : '<span class="text-muted small">بدون تصویر</span>'}</div>
          <div class="d-flex gap-2 mt-1"><button type="button" class="btn btn-sm btn-label-primary" data-pick="${id}">انتخاب</button><button type="button" class="btn btn-sm btn-label-secondary" data-clear="${id}">حذف</button></div><input type="hidden" data-f="${id}" value="${esc(val || '')}">${help}</div>`;
        case 'link': { const lv = val && typeof val === 'object' ? val : { href: val || '' };
          return `<div class="mb-3">${label}<input class="form-control mb-1" dir="ltr" data-f="${id}.href" value="${esc(lv.href || '')}" placeholder="/products یا https://…">
            ${f.label_field ? `<input class="form-control mb-1" data-f="${id}.label" data-lang="${L}" value="${esc((lv.label && lv.label[L]) || '')}" placeholder="متن لینک (${L})">` : ''}
            <div class="form-check form-switch"><input class="form-check-input" type="checkbox" data-f="${id}.new_tab" ${lv.new_tab ? 'checked' : ''}><label class="form-check-label">باز شدن در تب جدید</label></div>${help}</div>`; }
        case 'icon': return `<div class="mb-3">${label}<input class="form-control" dir="ltr" data-f="${id}" value="${esc(val || '')}" placeholder="مثلاً Gauge">${help}</div>`;
        case 'entity': return `<div class="mb-3">${label}<select class="form-select" data-ent="${f.entity}" data-f="${id}" ${f.multiple ? 'multiple size="5"' : ''}><option value="">…</option></select>${help}</div>`;
        case 'repeater': { const rows = Array.isArray(val) ? val : [];
          return `<div class="mb-3">${label}<div class="pb-rep" data-rep="${id}">${rows.map((r, i) => `<div class="card mb-2 pb-rep-row"><div class="card-header py-2 d-flex align-items-center gap-1">
              <span class="flex-grow-1 small fw-semibold">${esc(lbl(f.item_label) || 'مورد')} ${i + 1}</span>
              <button type="button" class="btn btn-icon btn-xs" data-rep-act="up" data-rep-id="${id}" data-i="${i}"><i class="ti ti-arrow-up"></i></button>
              <button type="button" class="btn btn-icon btn-xs" data-rep-act="down" data-rep-id="${id}" data-i="${i}"><i class="ti ti-arrow-down"></i></button>
              <button type="button" class="btn btn-icon btn-xs text-danger" data-rep-act="del" data-rep-id="${id}" data-i="${i}"><i class="ti ti-trash"></i></button></div>
              <div class="card-body pb-2">${(f.fields || []).map((sf) => fieldHtml(sf, r[sf.name], { id: `${id}.${i}.${sf.name}` })).join('')}</div></div>`).join('')}
            ${rows.length < (f.max_rows || 60) ? `<button type="button" class="btn btn-sm btn-label-primary" data-rep-act="add" data-rep-id="${id}"><i class="ti ti-plus me-1"></i>افزودن</button>` : ''}</div>${help}</div>`; }
      }
      return '';
    }

    /* settings are addressed by "<root>.<name>[.<i>.<name>…]" paths relative to the edited object */
    function getAt(obj, path) { return path.reduce((o, k) => (o === undefined || o === null ? undefined : o[k]), obj); }
    function fieldAt(fields, path) {
      let fs = fields, f;
      for (let i = 0; i < path.length; i++) {
        const seg = path[i];
        if (/^\d+$/.test(seg)) continue;
        f = fs.find((x) => x.name === seg); if (!f) return null;
        if (f.type === 'repeater') fs = f.fields || []; else if (f.type === 'link') return f;
      }
      return f;
    }
    function setAt(settings, path, value) {
      let o = settings;
      for (let i = 0; i < path.length - 1; i++) { const k = path[i], nk = path[i + 1]; if (o[k] === undefined || o[k] === null) o[k] = /^\d+$/.test(nk) ? [] : {}; o = o[k]; }
      o[path[path.length - 1]] = value;
    }

    function renderPanel() {
      const right = $('#pb-right');
      const idx = index(); const hit = S.sel && idx.get(S.sel);
      if (!hit) { right.innerHTML = `<div class="p-4 text-center text-muted"><i class="ti ti-pointer fs-1 d-block mb-2"></i>روی یک ردیف، ستون یا المان در پیش‌نمایش کلیک کنید.<br><br>
        <button class="btn btn-primary" id="pb-first-row"><i class="ti ti-plus me-1"></i>افزودن ردیف</button></div>`; right.querySelector('#pb-first-row').onclick = () => addRow(S.layout.sections.length); return; }
      const o = hit.o;
      o.common = o.common || {};
      const isRow = hit.kind === 'section' || (hit.kind === 'widget' && o.type === 'inner_row');
      const cfKind = hit.kind === 'widget' ? 'widget' : hit.kind;
      let contentFields, title;
      if (hit.kind === 'widget' && !isRow) { const wd = W[o.type]; contentFields = wd ? wd.fields : []; title = wd ? lbl(wd.label) : o.type + ' (ناشناخته)'; }
      else if (hit.kind === 'column') { contentFields = M.column_fields || []; title = 'ستون'; }
      else if (hit.kind === 'section') { contentFields = M.section_fields || []; title = 'ردیف'; }
      else { contentFields = []; title = 'ردیف داخلی'; }
      const tabFields = {
        content: contentFields,
        style: (CF[cfKind] || []).filter((f) => f.group === 'style'),
        motion: (CF[cfKind] || []).filter((f) => f.group === 'motion'),
        advanced: (CF[cfKind] || []).filter((f) => f.group === 'advanced'),
      };
      const tab = S.tab;
      const fields = tabFields[tab] || [];
      const needsLang = JSON.stringify(fields).includes('"i18n":true') || JSON.stringify(fields).includes('"label_field":true');
      const tabsHtml = TABS.map(([k, t]) => `<button class="nav-link ${k === tab ? 'active' : ''}" data-ptab="${k}">${k === 'content' && (isRow || hit.kind === 'column') ? 'چیدمان' : t}</button>`).join('');
      let layoutHtml = '';
      if (tab === 'content' && isRow) layoutHtml = `<div class="mb-3"><label class="form-label">ساختار ستون‌ها</label><button class="btn btn-label-primary w-100" id="pb-restruct"><i class="ti ti-layout-columns me-1"></i>${o.columns.map((c) => c.span).join(' + ')} — تغییر ساختار</button></div>`;
      if (tab === 'content' && hit.kind === 'column') {
        const sel = (dev, withAuto) => `<select class="form-select form-select-sm" data-span="${dev}">${withAuto ? '<option value="">خودکار</option>' : ''}${Array.from({ length: 12 }, (_, i) => i + 1).map((n) => `<option value="${n}" ${o[devSpanKey(dev)] === n ? 'selected' : ''}>${n}/12</option>`).join('')}</select>`;
        layoutHtml = `<div class="mb-3"><label class="form-label">عرض ستون</label><div class="row g-2">
          <div class="col-4"><small class="text-muted">دسکتاپ</small>${sel('desktop', false)}</div>
          <div class="col-4"><small class="text-muted">تبلت</small>${sel('tablet', true)}</div>
          <div class="col-4"><small class="text-muted">موبایل</small>${sel('mobile', true)}</div></div>
          <div class="form-text">برای تغییر سریع، دستگیرهٔ بین دو ستون را در پیش‌نمایش بکشید.</div></div>`;
      }
      right.innerHTML = `<div class="pb-panel-head"><strong>${esc(title)}</strong>
          ${needsLang && langs.length > 1 ? `<div class="btn-group btn-group-sm ms-auto" id="pb-lang">${langs.map((l) => `<button class="btn ${l.code === S.lang ? 'btn-primary' : 'btn-label-primary'}" data-l="${l.code}">${esc(l.code.toUpperCase())}</button>`).join('')}</div>` : ''}</div>
        <div class="nav nav-tabs pb-ptabs">${tabsHtml}</div>
        <div class="p-3" id="pb-form">
          ${layoutHtml}
          ${hit.kind === 'widget' && !isRow && !W[o.type] ? '<div class="alert alert-warning">این نوع المان در قالب فعلی فرانت وجود ندارد؛ داده‌هایش حفظ می‌شود ولی نمایش داده نخواهد شد.</div>' : ''}
          ${fields.map((f) => fieldHtml(f, (tab === 'content' ? o.settings : o.common)[f.name], { id: f.name })).join('') || (tab === 'content' && !layoutHtml ? '<div class="text-muted">این المان تنظیم محتوایی ندارد.</div>' : '')}</div>`;
      bindForm(right, { settings: tab === 'content' ? o.settings : o.common }, fields);
      right.querySelectorAll('[data-ptab]').forEach((b) => b.onclick = () => { S.tab = b.dataset.ptab; renderPanel(); });
      const rs = right.querySelector('#pb-restruct');
      if (rs) rs.onclick = () => pickStructure('تغییر ساختار ستون‌ها', (spans) => { applyStructure(o, spans); changed({ now: true }); renderAll(); });
      right.querySelectorAll('[data-span]').forEach((s) => s.onchange = () => { const k = devSpanKey(s.dataset.span); if (s.value) o[k] = +s.value; else delete o[k]; changed({ now: true }); renderTree(); });
    }

    function bindForm(right, target, fields) {
      const lg = right.querySelector('#pb-lang'); if (lg) lg.onclick = (e) => { const b = e.target.closest('[data-l]'); if (b) { S.lang = b.dataset.l; renderPanel(); } };
      const apply = (el) => {
        const path = el.dataset.f.split('.'); const f = fieldAt(fields, path); if (!f) return;
        let v;
        if (el.type === 'checkbox') v = el.checked;
        else if (el.tagName === 'SELECT' && el.multiple) v = [...el.selectedOptions].map((x) => x.value).filter(Boolean);
        else if (f.type === 'number') v = el.value === '' ? null : Number(el.value);
        else v = el.value;
        const last = path[path.length - 1];
        if (el.dataset.lang) { // translatable string: merge into {lang: text}
          const cur = getAt(target.settings, path); const m = cur && typeof cur === 'object' ? cur : (typeof cur === 'string' && cur ? { fa: cur } : {});
          m[el.dataset.lang] = v; v = m;
        }
        if (f.type === 'link' && (last === 'href' || last === 'new_tab' || last === 'label')) { // dotted link parts
          const base = path.slice(0, -1); const cur = getAt(target.settings, base); const lv = cur && typeof cur === 'object' ? cur : { href: cur || '' };
          lv[last] = v; setAt(target.settings, base, lv); return changed();
        }
        setAt(target.settings, path, v); changed();
      };
      right.querySelectorAll('[data-f]').forEach((el) => { const ev = el.type === 'checkbox' || el.tagName === 'SELECT' ? 'change' : 'input'; el.addEventListener(ev, () => apply(el)); });
      right.querySelectorAll('[data-fc]').forEach((el) => el.addEventListener('input', () => { const t = right.querySelector(`[data-f="${el.dataset.fc}"]`); t.value = el.value; apply(t); }));
      right.querySelectorAll('[data-clear]').forEach((b) => b.addEventListener('click', () => { const t = right.querySelector(`[data-f="${b.dataset.clear}"]`); t.value = ''; apply(t); renderPanel(); }));
      right.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', () => Admin.pickMedia((url) => { const t = right.querySelector(`[data-f="${b.dataset.pick}"]`); t.value = url; apply(t); renderPanel(); })));
      right.querySelectorAll('[data-rt]').forEach((g) => g.addEventListener('click', (e) => {
        const b = e.target.closest('[data-tag]'); if (!b) return;
        const ta = right.querySelector(`textarea[data-f="${g.dataset.rt}"]`); const s = ta.selectionStart, en = ta.selectionEnd, sel = ta.value.slice(s, en) || 'متن';
        const t = b.dataset.tag; const ins = t === 'a' ? `<a href="https://">${sel}</a>` : t === 'ul' ? `<ul><li>${sel}</li></ul>` : `<${t}>${sel}</${t}>`;
        ta.setRangeText(ins, s, en, 'end'); ta.dispatchEvent(new Event('input'));
      }));
      right.querySelectorAll('select[data-ent]').forEach(async (sel) => {
        const opts = await entityOptions(sel.dataset.ent); const path = sel.dataset.f.split('.'); const cur = getAt(target.settings, path);
        const curArr = Array.isArray(cur) ? cur : cur ? [cur] : [];
        sel.innerHTML = '<option value="">—</option>' + opts.map((o) => `<option value="${esc(o.value)}" ${curArr.includes(o.value) ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
      });
      right.querySelectorAll('[data-rep-act]').forEach((b) => b.addEventListener('click', () => {
        const path = b.dataset.repId.split('.'); const f = fieldAt(fields, path); let list = getAt(target.settings, path);
        if (!Array.isArray(list)) { list = []; setAt(target.settings, path, list); }
        const i = +b.dataset.i;
        if (b.dataset.repAct === 'add') list.push(clone(Object.fromEntries((f.fields || []).filter((x) => x.default !== undefined).map((x) => [x.name, x.default]))));
        if (b.dataset.repAct === 'del') list.splice(i, 1);
        if (b.dataset.repAct === 'up' && i > 0) [list[i - 1], list[i]] = [list[i], list[i - 1]];
        if (b.dataset.repAct === 'down' && i < list.length - 1) [list[i + 1], list[i]] = [list[i], list[i + 1]];
        changed({ now: true }); renderPanel();
      }));
    }

    /* ---------- node actions (tree buttons, on-page toolbar, keyboard) ---------- */
    function select(id, opts) {
      opts = opts || {};
      S.sel = id; if (id && index().get(id) && index().get(id).kind === 'column') S.insertCol = id;
      renderTree(); renderPanel(); if (!opts.fromFrame) post({ type: 'pb:highlight', id });
    }
    function doAction(a, id) {
      const hit = index().get(id); if (!hit) return;
      const list = hit.list; const i = list.findIndex((x) => x.id === id);
      if (a === 'save-template') return saveAsTemplate(hit.o);
      if (a === 'hide') hit.o.hidden = !hit.o.hidden;
      else if (a === 'up' && i > 0) [list[i - 1], list[i]] = [list[i], list[i - 1]];
      else if (a === 'down' && i < list.length - 1) [list[i + 1], list[i]] = [list[i], list[i + 1]];
      else if (a === 'dup') list.splice(i + 1, 0, freshIds(clone(hit.o)));
      else if (a === 'del') {
        list.splice(i, 1); if (S.sel === id || !index().has(S.sel)) S.sel = null;
        if (hit.kind === 'column' && hit.parent.columns.length) { const cols = hit.parent.columns; const base = Math.floor(12 / cols.length); cols.forEach((c, k) => { c.span = k === cols.length - 1 ? 12 - base * (cols.length - 1) : base; }); }
      } else return;
      changed({ now: true }); renderAll();
    }
    function insertAt(node, colId, at) {
      const hit = index().get(colId); if (!hit || hit.kind !== 'column') return false;
      hit.o.widgets.splice(Math.min(at, hit.o.widgets.length), 0, node); return true;
    }
    function dropWidget(drop, msg) {
      let node;
      if (drop === 'inner_row' || W[drop]) node = newWidget(drop); else return;
      if (msg.col !== undefined) { if (!insertAt(node, msg.col, msg.index)) return; }
      else { const s = newSection([12]); s.columns[0].widgets.push(node); S.layout.sections.splice(msg.row, 0, s); }
      S.sel = node.id; changed({ now: true }); renderAll();
    }
    function moveWidget(id, msg) {
      const hit = index().get(id); if (!hit || hit.kind !== 'widget') return;
      const list = hit.list; const from = list.indexOf(hit.o);
      if (msg.col !== undefined) {
        const dest = index().get(msg.col); if (!dest) return;
        if (hit.o.columns && JSON.stringify(hit.o).includes(`"${msg.col}"`)) return;   // can't drop a row into itself
        let at = msg.index;
        list.splice(from, 1);
        if (dest.o.widgets === list && from < at) at--;
        dest.o.widgets.splice(Math.min(at, dest.o.widgets.length), 0, hit.o);
      } else {
        list.splice(from, 1);
        const s = newSection([12]); s.columns[0].widgets.push(hit.o); S.layout.sections.splice(Math.min(msg.row, S.layout.sections.length), 0, s);
      }
      changed({ now: true }); renderAll();
    }
    function resizeCols(msg) {
      const idx = index(); const a = idx.get(msg.a), b = idx.get(msg.b); if (!a || !b) return;
      const k = devSpanKey(msg.device);
      a.o[k] = msg.spanA; b.o[k] = msg.spanB;
      // the pair shares one row at this width, so make sure every other column of it is explicit too (stable layout)
      changed({ now: true }); renderTree(); if (S.sel === msg.a || S.sel === msg.b) renderPanel();
    }

    const onMsg = (ev) => {
      if (!S.previewOrigin || ev.origin !== S.previewOrigin) return;
      const d = ev.data || {};
      switch (d.type) {
        case 'pb:ready':
          sendScale();
          post({ type: 'pb:labels', labels: Object.assign({ inner_row: 'ردیف داخلی' }, Object.fromEntries(M.widgets.map((w) => [w.type, lbl(w.label)]))) });
          post({ type: 'pb:highlight', id: S.sel }); break;
        case 'pb:select': if (typeof d.id === 'string' && index().has(d.id)) { S.tab = 'content'; select(d.id, { fromFrame: true }); } break;
        case 'pb:action': doAction(d.action, d.id); break;
        case 'pb:add-row': addRow(Math.max(0, Math.min(+d.index || 0, S.layout.sections.length))); break;
        case 'pb:add-template': pickTemplate(Math.max(0, Math.min(+d.index || 0, S.layout.sections.length))); break;
        case 'pb:add-widget': S.insertCol = d.col; showTab('widgets'); toast.ok('المان را انتخاب کنید یا روی صفحه بکشید'); break;
        case 'pb:dropped': dropWidget(d.drop, d); break;
        case 'pb:move': moveWidget(d.id, d); break;
        case 'pb:resize': resizeCols(d); break;
        case 'pb:key':
          if (d.key === 'Delete' && S.sel) doAction('del', S.sel);
          else if (d.ctrl && /z/i.test(d.key)) jump(d.shift ? 1 : -1);
          else if (d.ctrl && /y/i.test(d.key)) jump(1);
          else if (d.ctrl && /s/i.test(d.key)) save();
          break;
      }
    };
    window.addEventListener('message', onMsg);

    root.addEventListener('click', (e) => {
      const act = e.target.closest('[data-act]');
      if (act) { e.stopPropagation(); return doAction(act.dataset.act, act.dataset.id); }
      const row = e.target.closest('[data-sel]'); if (row && !e.target.closest('.pb-handle')) { S.tab = 'content'; select(row.dataset.sel); }
      if (e.target.closest('#pb-addsec')) addRow(S.layout.sections.length);
    });
    $('#pb-tabs').addEventListener('click', (e) => { const b = e.target.closest('[data-t]'); if (b) showTab(b.dataset.t); });
    function showTab(t) {
      root.querySelectorAll('#pb-tabs .nav-link').forEach((x) => x.classList.toggle('active', x.dataset.t === t));
      ['structure', 'widgets', 'templates'].forEach((k) => $('#pb-pane-' + k).classList.toggle('d-none', k !== t));
      if (t === 'templates') renderTemplates();
    }
    function renderAll() {
      renderTree(); renderPanel();
      if (S.sel !== S.postedSel) { S.postedSel = S.sel; post({ type: 'pb:highlight', id: S.sel }); }   // keep the on-page selection in step
    }

    /* ---------- top bar ---------- */
    $('#pb-undo').onclick = () => jump(-1); $('#pb-redo').onclick = () => jump(1);
    $('#pb-devices').addEventListener('click', (e) => { const b = e.target.closest('[data-d]'); if (!b) return; S.device = b.dataset.d;
      root.querySelectorAll('#pb-devices .btn').forEach((x) => x.classList.toggle('active', x === b)); fitFrame(); });
    $('#pb-anim').onclick = () => { S.anim = !S.anim; $('#pb-anim').classList.toggle('btn-primary', S.anim); $('#pb-anim').classList.toggle('btn-label-secondary', !S.anim); loadPreview(); };
    $('#pb-publish').onclick = async () => {
      await flush();
      const out = await safe(() => api.post(A + `/pages/${pid}/publish`)); if (out) { S.page = out; paintStatus(); toast.ok('صفحه منتشر شد'); }
    };
    const sch = $('#pb-schedule');
    if (sch) sch.onclick = (e) => { e.preventDefault();
      modal('زمان‌بندی انتشار', '<label class="form-label">تاریخ و ساعت انتشار (به وقت مرورگر شما)</label><input type="datetime-local" class="form-control" id="pb-when">', 'زمان‌بندی', async (el) => {
        const v = el.querySelector('#pb-when').value; if (!v) { toast.err('زمان را وارد کنید'); return false; }
        await flush();
        const out = await safe(() => api.post(A + `/pages/${pid}/publish`, { publish_at: new Date(v).toISOString() })); if (!out) return false;
        S.page = out; paintStatus(); toast.ok(out.status === 'scheduled' ? 'انتشار زمان‌بندی شد' : 'صفحه منتشر شد');
      }, 'modal-md'); };
    $('#pb-unpub').onclick = async (e) => { e.preventDefault(); if (!(await confirm('صفحه از سایت برداشته می‌شود (برای صفحه‌های سیستمی، نسخهٔ پیش‌فرض خود فرانت نمایش داده می‌شود).'))) return;
      const out = await safe(() => api.post(A + `/pages/${pid}/unpublish`)); if (out) { S.page = out; paintStatus(); toast.ok('لغو انتشار شد'); } };
    const reset = $('#pb-reset'); if (reset) reset.onclick = async (e) => { e.preventDefault(); if (!(await confirm('پیش‌نویس با طرح پیش‌فرض قالب جایگزین می‌شود.'))) return;
      const out = await safe(() => api.post(A + `/pages/${pid}/reset`)); if (out) { S.page = out; S.layout = out.layout; S.sel = null; pushHist(); renderAll(); paintStatus(); post({ type: 'pb:refresh' }); toast.ok('بازنشانی شد'); } };
    $('#pb-export').onclick = async (e) => { e.preventDefault(); const d = await safe(() => api.get(A + `/pages/${pid}/export`)); if (!d) return;
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' })); a.download = `page-${S.page.theme}-${S.page.slug.replace(/\//g, '_')}.json`; a.click(); };
    $('#pb-rev').onclick = async (e) => { e.preventDefault(); const revs = await safe(() => api.get(A + `/pages/${pid}/revisions`)); if (!revs) return;
      const m = modal('تاریخچهٔ انتشار', `<ul class="list-group">${revs.map((r) => `<li class="list-group-item d-flex align-items-center"><span class="flex-grow-1">${esc(Admin.dt.toJalali(r.created_at) || '')} <small class="text-muted">${esc(r.note || '')}</small></span><button class="btn btn-sm btn-label-primary" data-r="${r.id}">بازگردانی به پیش‌نویس</button></li>`).join('') || '<li class="list-group-item text-muted">نسخه‌ای نیست</li>'}</ul>`);
      m.el.addEventListener('click', async (ev) => { const b = ev.target.closest('[data-r]'); if (!b) return;
        const out = await safe(() => api.post(A + `/pages/${pid}/restore`, { revision_id: +b.dataset.r })); if (out) { S.page = out; S.layout = out.layout; S.sel = null; pushHist(); renderAll(); post({ type: 'pb:refresh' }); toast.ok('در پیش‌نویس بازگردانی شد'); m.hide(); } }); };
    $('#pb-settings').onclick = () => pageSettings();

    function pageSettings() {
      const p = S.page; const seo = p.seo || {}; const opt = p.options || {};
      const tl = (obj, l) => esc((obj && obj[l]) || '');
      modal('تنظیمات صفحه', `
        ${langs.map((l) => `<div class="mb-3"><label class="form-label">عنوان (${esc(l.code)})</label><input class="form-control" data-k="title.${l.code}" value="${tl(p.title, l.code)}"></div>`).join('')}
        ${p.kind === 'custom' ? `<div class="mb-3"><label class="form-label">نشانی (slug)</label><input class="form-control" dir="ltr" data-k="slug" value="${esc(p.slug)}"></div>` : `<div class="mb-3"><label class="form-label">نشانی</label><div><code>${esc(p.path)}</code></div></div>`}
        ${p.role === 'page' ? `<div class="form-check form-switch mb-1"><input class="form-check-input" type="checkbox" data-k="opt.hide_header" ${opt.hide_header ? 'checked' : ''}><label class="form-check-label">مخفی کردن هدر در این صفحه</label></div>
          <div class="form-check form-switch mb-3"><input class="form-check-input" type="checkbox" data-k="opt.hide_footer" ${opt.hide_footer ? 'checked' : ''}><label class="form-check-label">مخفی کردن فوتر در این صفحه</label></div>` : ''}
        <hr><h6>سئو</h6>
        ${langs.map((l) => `<div class="mb-3"><label class="form-label">عنوان سئو (${esc(l.code)})</label><input class="form-control" data-k="seo.title.${l.code}" value="${tl(seo.title, l.code)}"></div>
          <div class="mb-3"><label class="form-label">توضیحات سئو (${esc(l.code)})</label><textarea class="form-control" rows="2" data-k="seo.description.${l.code}">${tl(seo.description, l.code)}</textarea></div>`).join('')}
        <div class="mb-3"><label class="form-label">تصویر OG</label><div class="input-group"><input class="form-control" dir="ltr" data-k="seo.og_image" value="${esc(seo.og_image || '')}"><button class="btn btn-label-primary" type="button" id="ps-pick">انتخاب</button></div></div>
        <div class="form-check form-switch"><input class="form-check-input" type="checkbox" data-k="seo.noindex" ${seo.noindex ? 'checked' : ''}><label class="form-check-label">noindex</label></div>`, 'ذخیره', async (el) => {
        const g = (k) => el.querySelector(`[data-k="${k}"]`);
        const pack = (pre) => Object.fromEntries(langs.map((l) => [l.code, g(`${pre}.${l.code}`).value]));
        const payload = { title: pack('title'), seo: { title: pack('seo.title'), description: pack('seo.description'), og_image: g('seo.og_image').value, noindex: g('seo.noindex').checked } };
        if (g('slug')) payload.slug = g('slug').value;
        if (g('opt.hide_header')) payload.options = { hide_header: g('opt.hide_header').checked, hide_footer: g('opt.hide_footer').checked };
        await flush();
        try { const out = await api.put(A + '/pages/' + pid, payload); S.page = out; paintStatus(); toast.ok('ذخیره شد');
          if (out.slug !== p.slug) loadPreview(); } catch (e) { toast.err(e.message); return false; }
      }).el.querySelector('#ps-pick').onclick = () => Admin.pickMedia((url) => { document.querySelector('.modal.show [data-k="seo.og_image"]').value = url; });
    }

    /* ---------- preview iframe ---------- */
    async function loadPreview() {
      const body = pageDef.sample ? { sample: S.sample } : {};
      if (pageDef.sample && !S.sample) { $('#pb-frame').srcdoc = '<p style="font:14px system-ui;padding:2rem;direction:rtl">برای پیش‌نمایش این قالب، از بالا یک نمونه انتخاب کنید.</p>'; return; }
      const out = await safe(() => api.post(A + `/pages/${pid}/preview-url`, body)); if (!out) return;
      S.previewOrigin = out.origin;
      const url = out.url + (S.anim ? '&anim=1' : '');
      $('#pb-frame').removeAttribute('srcdoc'); $('#pb-frame').src = url;
      $('#pb-open').href = out.url.replace('&builder=1', '');
    }
    setInterval(loadPreview, 45 * 60 * 1000);   // preview tokens live 1 h
    const sampleSel = $('#pb-sample');
    if (sampleSel) entityOptions(pageDef.sample).then((opts) => {
      sampleSel.innerHTML = '<option value="">نمونهٔ پیش‌نمایش…</option>' + opts.map((o) => `<option value="${esc(o.value)}" ${o.value === S.sample ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
      sampleSel.onchange = () => { S.sample = sampleSel.value; sessionStorage.setItem('pb-sample-' + pid, S.sample); loadPreview(); };
      if (!S.sample && opts.length) { S.sample = opts[0].value; sampleSel.value = S.sample; loadPreview(); }
    });

    document.addEventListener('keydown', (e) => {
      const inField = /INPUT|TEXTAREA|SELECT/.test((e.target || {}).tagName || '');
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
      else if (!inField && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); jump(e.shiftKey ? 1 : -1); }
      else if (!inField && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); jump(1); }
    });
    window.addEventListener('beforeunload', (e) => { if (S.dirty || S.saving) { e.preventDefault(); e.returnValue = ''; } });

    paintStatus(); renderPalette(''); renderAll(); updBtns(); fitFrame(); loadPreview();
  };
})();
