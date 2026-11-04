/* Generic list + form pages for entities declared with app/core/entity.py.
   Everything is driven by GET <api>/schema; data via <api> (list), <api>/<id>, POST, PUT, DELETE, POST <id>/toggle. */
(function () {
  'use strict';
  const { api, toast, esc, safe } = Admin;
  const root = document.getElementById('entity-app');
  if (!root) return;
  const mode = root.dataset.mode;
  const apiBase = root.dataset.api;
  const pageBase = root.dataset.page;
  const entityId = root.dataset.id ? parseInt(root.dataset.id, 10) : null;

  const STATUS = { draft: ['پیش‌نویس', 'secondary'], published: ['منتشرشده', 'success'] };

  // --------------------------------------------------------------------------------------------
  // list
  // --------------------------------------------------------------------------------------------
  async function initList() {
    const schema = await api.get(apiBase + '/schema');
    const ent = schema.entity;
    const cols = [{ title: 'عنوان', cls: 'col-title' }];
    ent.columns.forEach((h) => cols.push({ title: h }));
    const showStatus = ent.status && !ent.columns.includes('وضعیت');   // some entities already print their own status column
    if (showStatus) cols.push({ title: 'وضعیت' });
    if (ent.active) cols.push({ title: 'فعال' });
    cols.push({ title: 'عملیات', cls: 'text-nowrap' });

    root.innerHTML = `
      <div class="card">
        <div class="card-header d-flex flex-wrap gap-3 justify-content-between align-items-center">
          <div><h5 class="card-title mb-0">${esc(ent.plural)}</h5>${ent.help ? `<small class="text-muted">${esc(ent.help)}</small>` : ''}</div>
          <div class="d-flex flex-wrap gap-2 align-items-center">
            ${ent.searchable ? '<input type="search" id="q" class="form-control" style="width:220px" placeholder="جستجو...">' : ''}
            ${schema.filters.map((f) => `<select class="form-select flt" style="width:auto" data-col="${esc(f.col)}"><option value="">${esc(f.label)}: همه</option>${f.options.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('')}</select>`).join('')}
            ${ent.sorts.length ? `<select id="sort" class="form-select" style="width:auto"><option value="">ترتیب پیش‌فرض</option>${ent.sorts.map((s) => `<option>${esc(s)}</option>`).join('')}</select>` : ''}
            <a class="btn btn-primary" href="${esc(pageBase)}/create"><i class="ti ti-plus me-1"></i>${esc(ent.label)} جدید</a>
          </div>
        </div>
        <div id="tbl-sk">${Admin.sk.rows(Math.min(ent.per_page, 8), cols.length)}</div>
        <div class="table-responsive sk-hide" id="tbl-wrap"><table class="table table-hover" id="tbl" style="width:100%"><thead><tr>${cols.map((c) => `<th>${esc(c.title)}</th>`).join('')}</tr></thead><tbody></tbody></table></div>
      </div>`;

    const state = { q: '', sort: '', filters: {} };
    const $tbl = $('#tbl');
    $tbl.on('preXhr.dt', () => $('#tbl-wrap').addClass('dt-loading'));
    $tbl.on('xhr.dt', () => { $('#tbl-wrap').removeClass('dt-loading sk-hide'); $('#tbl-sk').remove(); });
    const dt = $tbl.DataTable({
      processing: false, serverSide: true, responsive: true, ordering: false, searching: false, lengthChange: false,
      pageLength: ent.per_page, dom: 't<"row mx-2 py-2"<"col-md-6"i><"col-md-6"p>>',
      language: { emptyTable: 'موردی یافت نشد', processing: 'در حال بارگذاری...' },
      ajax: (data, cb) => {
        const params = { page: Math.floor(data.start / data.length) + 1, per_page: data.length, q: state.q, sort: state.sort };
        Object.keys(state.filters).forEach((c) => (params['f_' + c] = state.filters[c]));
        api.get(apiBase + api.qs(params), { full: true }).then((res) => {
          cb({ draw: data.draw, recordsTotal: res.meta.total, recordsFiltered: res.meta.total, data: res.data });
        }).catch((e) => { toast.err(e.message); cb({ draw: data.draw, recordsTotal: 0, recordsFiltered: 0, data: [] }); });
      },
      columns: [
        { data: null, className: 'col-title', responsivePriority: 1, render: (_d, _t, r) => `<a href="${esc(pageBase)}/${r.id}/edit" class="fw-medium">${esc(r.title)}</a>` },
        ...ent.columns.map((_h, i) => ({ data: null, render: (_d, _t, r) => esc(r.cells[i]) })),
        ...(showStatus ? [{ data: null, render: (_d, _t, r) => { const s = STATUS[r.status] || [r.status, 'secondary']; return `<span class="badge bg-label-${s[1]}">${esc(s[0])}</span>`; } }] : []),
        ...(ent.active ? [{ data: null, render: (_d, _t, r) => `<div class="form-check form-switch"><input class="form-check-input tg" type="checkbox" data-id="${r.id}" ${r.is_active ? 'checked' : ''}></div>` }] : []),
        { data: null, className: 'text-nowrap', responsivePriority: 2, render: (_d, _t, r) => `
            <a class="btn btn-sm btn-icon btn-text-secondary" title="ویرایش" href="${esc(pageBase)}/${r.id}/edit"><i class="ti ti-edit"></i></a>
            ${r.view_url ? `<a class="btn btn-sm btn-icon btn-text-secondary" title="مشاهده در سایت" target="_blank" href="${esc(r.view_url)}"><i class="ti ti-external-link"></i></a>` : ''}
            ${(r.actions || []).map((a) => `<a class="btn btn-sm btn-text-secondary" href="${esc(a.url)}">${esc(a.label)}</a>`).join('')}
            <button class="btn btn-sm btn-icon btn-text-danger del" title="حذف" data-id="${r.id}" data-title="${esc(r.title)}"><i class="ti ti-trash"></i></button>` },
      ],
    });

    let timer;
    root.querySelector('#q')?.addEventListener('input', (e) => { clearTimeout(timer); timer = setTimeout(() => { state.q = e.target.value.trim(); dt.ajax.reload(); }, 350); });
    root.querySelector('#sort')?.addEventListener('change', (e) => { state.sort = e.target.value; dt.ajax.reload(); });
    root.querySelectorAll('.flt').forEach((s) => s.addEventListener('change', () => { state.filters[s.dataset.col] = s.value; dt.ajax.reload(); }));

    $tbl.on('change', '.tg', async function () {
      const el = this;
      const r = await safe(() => api.post(`${apiBase}/${el.dataset.id}/toggle`));
      if (r) toast.ok('وضعیت تغییر کرد'); else el.checked = !el.checked;
    });
    $tbl.on('click', '.del', async function () {
      const { id, title } = this.dataset;
      if (!(await Admin.confirm(`«${title}» حذف شود؟ این کار قابل بازگشت نیست.`))) return;
      if (await safe(() => api.del(`${apiBase}/${id}`))) { toast.ok(`${ent.label} حذف شد`); dt.ajax.reload(null, false); }
    });
  }

  // --------------------------------------------------------------------------------------------
  // form
  // --------------------------------------------------------------------------------------------
  let SCHEMA, LANGS, OPTIONS, HIDDEN, activeLang = 'fa';

  function listToText(f, v) { return (v || []).join(f.kind === 'paragraphs' ? '\n\n' : '\n'); }
  function textToList(f, t) {
    const parts = f.kind === 'paragraphs' ? t.split(/\r?\n\s*\r?\n/) : t.split(/\r?\n/);
    return parts.map((x) => x.trim()).filter(Boolean);
  }

  /** one input element for (field, language-or-null, value) */
  function inputHtml(f, name, value, lang) {
    const dir = lang ? (LANGS.find((l) => l.code === lang) || {}).direction || 'rtl' : (f.ltr ? 'ltr' : 'rtl');
    const dattr = `data-name="${esc(name)}"${lang ? ` data-lang-input="${lang}"` : ''}`;
    const ltr = dir === 'ltr' ? ' ltr-input' : '';
    const opt = (list, cur, blank) => `${blank ? '<option value="">—</option>' : ''}${(list || []).map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(cur) ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}`;
    const k = f.kind;
    if (k === 'textarea') return `<textarea class="form-control${ltr}" rows="${f.rows || 3}" ${dattr} dir="${dir}">${esc(value)}</textarea>`;
    if (f.is_list) return `<textarea class="form-control${ltr}" rows="${f.rows > 3 ? f.rows : 5}" ${dattr} dir="${dir}" placeholder="${k === 'paragraphs' ? 'پاراگراف‌ها را با یک خط خالی جدا کنید' : 'هر مورد در یک خط'}">${esc(listToText(f, value))}</textarea>`;
    if (k === 'bool') return `<div class="form-check form-switch"><input class="form-check-input" type="checkbox" ${dattr} ${value ? 'checked' : ''}></div>`;
    if (k === 'select') return `<select class="form-select" ${dattr}>${opt(OPTIONS[f._optkey || f.name], value, !f.required)}</select>`;
    if (k === 'fk') return `<select class="form-select" ${dattr}>${opt(OPTIONS[f._optkey || f.name], value, true)}</select>`;
    if (k === 'datetime') return `<div class="input-group"><input type="text" class="form-control ltr-input js-dt" ${dattr} value="${esc(Admin.dt.toJalali(value))}" autocomplete="off"><button type="button" class="btn btn-outline-secondary dt-clear" title="پاک کردن"><i class="ti ti-x"></i></button></div>`;
    if (k === 'int' || k === 'float') return `<input type="number" step="${k === 'float' ? 'any' : '1'}" class="form-control ltr-input" ${dattr} value="${value === null || value === undefined ? '' : esc(value)}">`;
    if (k === 'media') return `<div class="input-group"><input type="text" class="form-control ltr-input" ${dattr} value="${esc(value)}" placeholder="/assets/uploads/..."><button type="button" class="btn btn-outline-secondary media-pick" ${Admin.pickMedia ? '' : 'hidden'}><i class="ti ti-photo"></i></button></div>`;
    const type = k === 'email' ? 'email' : (k === 'url' ? 'url' : 'text');
    return `<input type="${type}" class="form-control${ltr}" ${dattr} dir="${dir}" value="${esc(value)}" ${f.max ? `maxlength="${f.max}"` : ''} placeholder="${esc(f.placeholder || '')}">`;
  }

  function fieldHtml(f, value, optKey) {
    f._optkey = optKey;
    const wide = ['textarea', 'media'].includes(f.kind) || f.is_list;
    let body;
    if (f.i18n) {
      body = LANGS.map((l) => `<div class="lang-pane" data-lang="${l.code}" ${l.code === activeLang ? '' : 'hidden'}>${inputHtml(f, f.name, (value || {})[l.code] !== undefined ? value[l.code] : (f.is_list ? [] : ''), l.code)}</div>`).join('');
    } else {
      body = inputHtml(f, f.name, value, null);
    }
    const star = f.required ? ' <span class="text-danger">*</span>' : '';
    const pub = f.publish_required ? ' <small class="text-muted">(برای انتشار)</small>' : '';
    return `<div class="${wide ? 'col-12' : 'col-md-6'} mb-3 fld" data-field="${esc(f.name)}" data-kind="${f.kind}" data-i18n="${f.i18n ? 1 : 0}">
      ${f.kind === 'bool' ? '' : `<label class="form-label">${esc(f.label)}${star}${pub}</label>`}
      ${f.kind === 'bool' ? `<label class="form-label d-block">${esc(f.label)}</label>` : ''}
      ${body}
      ${f.help ? `<div class="form-text">${esc(f.help)}</div>` : ''}
      <div class="field-error" hidden></div></div>`;
  }

  function rowHtml(ch, rowValues, idx) {
    return `<div class="repeater-row" data-child="${ch.key}">
      <div class="repeater-head"><strong>${esc(ch.item_label)} <span class="row-no">${idx + 1}</span></strong>
        <div class="btn-group btn-group-sm"><button type="button" class="btn btn-outline-secondary row-up" title="بالا"><i class="ti ti-arrow-up"></i></button>
        <button type="button" class="btn btn-outline-secondary row-down" title="پایین"><i class="ti ti-arrow-down"></i></button>
        <button type="button" class="btn btn-outline-danger row-del" title="حذف"><i class="ti ti-trash"></i></button></div></div>
      <div class="row">${ch.fields.map((f) => fieldHtml(f, rowValues[f.name], f.name)).join('')}</div></div>`;
  }

  function childHtml(ch, rows) {
    return `<div class="card mb-4 child-card" data-child-key="${ch.key}"><div class="card-header d-flex justify-content-between align-items-center">
      <div><h6 class="mb-0">${esc(ch.label)}</h6>${ch.help ? `<small class="text-muted">${esc(ch.help)}</small>` : ''}</div>
      <button type="button" class="btn btn-sm btn-label-primary child-add"><i class="ti ti-plus me-1"></i>افزودن</button></div>
      <div class="card-body child-rows">${(rows || []).map((r, i) => rowHtml(ch, r, i)).join('')}</div></div>`;
  }

  function readInput(f, el, lang) {
    if (f.kind === 'bool') return el.checked;
    if (f.kind === 'datetime') return Admin.dt.read(el);
    const v = el.value;
    if (f.is_list) return textToList(f, v);
    if (f.kind === 'int' || f.kind === 'float') return v === '' ? null : Number(v);
    if (f.kind === 'fk') return v === '' ? null : Number(v);
    return v;
  }

  function readField(f, scope) {
    if (f.i18n) {
      const out = {};
      scope.querySelectorAll(`.fld[data-field="${CSS.escape(f.name)}"] [data-lang-input]`).forEach((el) => { out[el.dataset.langInput] = readInput(f, el); });
      return out;
    }
    const el = scope.querySelector(`.fld[data-field="${CSS.escape(f.name)}"] [data-name]`);
    return el ? readInput(f, el) : undefined;
  }

  function collect(form) {
    const ent = SCHEMA.entity;
    const data = {};
    const top = form.querySelector('#fields-main');
    ent.fields.forEach((f) => {
      if (HIDDEN.includes(f.name)) return;
      const v = readField(f, top);
      if (v !== undefined) data[f.name] = v;
    });
    if (ent.status) {
      data.status = form.querySelector('[name=status]').value;
      data.published_at = Admin.dt.read(form.querySelector('[name=published_at]'));
    }
    if (ent.active) data.is_active = form.querySelector('[name=is_active]').checked;
    ent.children.forEach((ch) => {
      data[ch.key] = [...form.querySelectorAll(`.child-card[data-child-key="${ch.key}"] .repeater-row`)].map((row) => {
        const o = {};
        const holder = row.querySelector(':scope > .row');
        ch.fields.forEach((f) => { const v = readField(f, holder); if (v !== undefined) o[f.name] = v; });
        return o;
      });
    });
    return data;
  }

  function showErrors(form, fields) {
    form.querySelectorAll('.field-error').forEach((e) => { e.hidden = true; e.textContent = ''; });
    form.querySelectorAll('.is-invalid-field').forEach((e) => e.classList.remove('is-invalid-field'));
    let first = null, general = [];
    Object.keys(fields || {}).forEach((key) => {
      let fld = null;
      const m = key.match(/^(.+)-(\d+)-(.+)$/);
      if (m) {
        const row = form.querySelectorAll(`.child-card[data-child-key="${CSS.escape(m[1])}"] .repeater-row`)[parseInt(m[2], 10)];
        fld = row && row.querySelector(`.fld[data-field="${CSS.escape(m[3])}"]`);
      } else {
        fld = form.querySelector(`#fields-main .fld[data-field="${CSS.escape(key)}"]`) || form.querySelector(`[name="${CSS.escape(key)}"]`)?.closest('.fld-extra');
      }
      if (fld) {
        fld.classList.add('is-invalid-field');
        const e = fld.querySelector('.field-error');
        e.textContent = fields[key]; e.hidden = false;
        first = first || fld;
      } else general.push(fields[key]);
    });
    if (general.length) toast.err(general.join(' | '));
    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function setLang(form, code) {
    activeLang = code;
    form.querySelectorAll('.lang-pane').forEach((p) => { p.hidden = p.dataset.lang !== code; });
    form.querySelectorAll('.lang-tab').forEach((t) => t.classList.toggle('active', t.dataset.lang === code));
  }

  function updateMissing(form) {
    LANGS.forEach((l) => {
      const dot = form.querySelector(`.lang-tab[data-lang="${l.code}"] .i18n-missing-dot`);
      if (!dot) return;
      const inputs = [...form.querySelectorAll(`[data-lang-input="${l.code}"]`)];
      dot.hidden = inputs.length === 0 || inputs.some((i) => i.value.trim());
    });
  }

  async function initForm() {
    const settings = mode === 'settings';   // single-record page (site settings): GET/PUT <api>, fields grouped in tabs
    const groups = [];
    if (settings) {
      const d = await api.get(apiBase);
      SCHEMA = { entity: d.entity, languages: d.languages, defaults: d.values, options: d.options, hidden: [] };
      groups.push(...d.groups);
    } else {
      SCHEMA = await api.get(apiBase + '/schema' + location.search);
    }
    const ent = SCHEMA.entity;
    LANGS = SCHEMA.languages;
    let item = { id: null, values: SCHEMA.defaults, options: SCHEMA.options, hidden: SCHEMA.hidden, view_url: null, preview_url: null };
    if (mode === 'edit') item = await api.get(`${apiBase}/${entityId}`);
    item.panels = item.panels || [];
    OPTIONS = item.options;
    HIDDEN = item.hidden || [];
    const v = item.values;
    const fields = ent.fields.filter((f) => !HIDDEN.includes(f.name));
    const sidebar = ent.status || ent.active || (item.panels || []).length > 0;
    const multiLang = LANGS.length > 1 && (fields.some((f) => f.i18n) || ent.children.some((c) => c.fields.some((f) => f.i18n)));

    root.innerHTML = `
      <form id="eform" novalidate>
        <div class="d-flex flex-wrap justify-content-between align-items-center mb-3">
          <h4 class="mb-0">${settings ? esc(ent.label) : `${mode === 'edit' ? 'ویرایش' : ''} ${esc(ent.label)}${mode === 'edit' ? ` <small class="text-muted">#${entityId}</small>` : ' جدید'}`}</h4>
          <div class="d-flex gap-2">
            ${item.view_url ? `<a class="btn btn-label-secondary" target="_blank" href="${esc(item.view_url)}"><i class="ti ti-external-link me-1"></i>مشاهده</a>` : ''}
            ${item.preview_url ? `<a class="btn btn-label-info" target="_blank" href="${esc(item.preview_url)}"><i class="ti ti-eye me-1"></i>پیش‌نمایش پیش‌نویس</a>` : ''}
            ${settings ? '' : `<a class="btn btn-outline-secondary" href="${esc(pageBase)}">بازگشت به فهرست</a>`}
          </div>
        </div>
        ${multiLang ? `<ul class="nav nav-pills mb-3" id="lang-tabs">${LANGS.map((l) => `<li class="nav-item"><a href="javascript:void(0)" class="nav-link lang-tab ${l.code === activeLang ? 'active' : ''}" data-lang="${l.code}">${esc(l.native_name || l.code)} <span class="i18n-missing-dot" title="ترجمه ناقص">●</span></a></li>`).join('')}</ul>` : ''}
        <div class="row">
          <div class="col-lg-${sidebar ? '9' : '12'}">
            <div class="card mb-4"><div class="card-body">${settings ? `
              <ul class="nav nav-tabs mb-4 flex-wrap" role="tablist">${groups.map((g, i) => `<li class="nav-item"><button type="button" class="nav-link ${i === 0 ? 'active' : ''}" data-bs-toggle="tab" data-bs-target="#grp-${g.key}">${esc(g.title)}</button></li>`).join('')}</ul>
              <div class="tab-content p-0 shadow-none" id="fields-main">${groups.map((g, i) => `<div class="tab-pane fade ${i === 0 ? 'show active' : ''}" id="grp-${g.key}"><div class="row">${g.fields.map((n) => fields.find((f) => f.name === n)).filter(Boolean).map((f) => fieldHtml(f, v[f.name], f.name)).join('')}</div></div>`).join('')}</div>`
              : `<div class="row" id="fields-main">${fields.map((f) => fieldHtml(f, v[f.name], f.name)).join('')}</div>`}</div></div>
            ${ent.children.map((ch) => childHtml(ch, v[ch.key])).join('')}
          </div>
          ${sidebar ? `<div class="col-lg-3">${ent.status || ent.active ? `<div class="card mb-4"><div class="card-body">
            ${ent.status ? `<div class="mb-3 fld-extra"><label class="form-label">وضعیت</label><select name="status" class="form-select"><option value="draft" ${v.status === 'draft' ? 'selected' : ''}>پیش‌نویس</option><option value="published" ${v.status === 'published' ? 'selected' : ''}>منتشرشده</option></select><div class="field-error" hidden></div></div>
            <div class="mb-3 fld-extra"><label class="form-label">زمان انتشار</label><div class="input-group"><input type="text" name="published_at" class="form-control ltr-input js-dt" value="${esc(Admin.dt.toJalali(v.published_at))}" autocomplete="off"><button type="button" class="btn btn-outline-secondary dt-clear" title="پاک کردن"><i class="ti ti-x"></i></button></div><div class="form-text">زمان به‌صورت UTC ثبت می‌شود؛ خالی = همین حالا</div><div class="field-error" hidden></div></div>` : ''}
            ${ent.active ? `<div class="form-check form-switch fld-extra"><input class="form-check-input" type="checkbox" name="is_active" id="is_active" ${v.is_active ? 'checked' : ''}><label class="form-check-label" for="is_active">فعال</label></div>` : ''}
          </div></div>` : ''}
          ${(item.panels || []).map((p) => `<div class="card mb-4"><div class="card-body"><h6>${esc(p.title)}</h6>${p.text ? `<p class="small text-muted">${esc(p.text)}</p>` : ''}${(p.links || []).map((l) => `<a class="btn btn-label-primary w-100 mb-2" href="${esc(l.url)}">${esc(l.label)}</a>`).join('')}</div></div>`).join('')}
          </div>` : ''}
        </div>
        <div class="form-sticky-actions d-flex gap-2">
          <button type="submit" class="btn btn-primary" data-after="stay"><i class="ti ti-device-floppy me-1"></i>ذخیره</button>
          ${settings ? '' : '<button type="submit" class="btn btn-label-primary" data-after="close">ذخیره و بستن</button>'}
          ${mode === 'edit' ? '<button type="button" class="btn btn-label-danger ms-auto" id="btn-del"><i class="ti ti-trash me-1"></i>حذف</button>' : ''}
        </div>
      </form>`;

    const form = root.querySelector('#eform');
    form.querySelectorAll('select.form-select').forEach((s) => { if (s.options.length > 8 && $.fn.select2) $(s).select2({ dir: 'rtl', width: '100%', dropdownParent: $(s).parent() }); });
    form.querySelectorAll('.lang-tab').forEach((t) => t.addEventListener('click', () => setLang(form, t.dataset.lang)));
    form.addEventListener('input', () => updateMissing(form));
    updateMissing(form);

    // Jalali date/time pickers (display Jalali, send Gregorian — see Admin.dt)
    const initDates = (scope) => {
      if (!window.flatpickr) return;
      scope.querySelectorAll('.js-dt').forEach((el) => Admin.dt.init(el));
    };
    initDates(form);
    form.addEventListener('click', (e) => {
      const b = e.target.closest('.dt-clear');
      if (!b) return;
      const inp = b.closest('.input-group').querySelector('.js-dt');
      if (inp._flatpickr) inp._flatpickr.clear(); else inp.value = '';
      dirty = true;
    });

    // media picker (library modal)
    form.addEventListener('click', (e) => {
      const b = e.target.closest('.media-pick');
      if (!b || !Admin.pickMedia) return;
      const input = b.closest('.input-group').querySelector('input');
      Admin.pickMedia((url) => { input.value = url; input.dispatchEvent(new Event('input', { bubbles: true })); });
    });

    // repeaters
    const renumber = (card) => card.querySelectorAll('.repeater-row').forEach((r, i) => { r.querySelector('.row-no').textContent = i + 1; });
    form.addEventListener('click', (e) => {
      const card = e.target.closest('.child-card');
      if (!card) return;
      const ch = ent.children.find((c) => c.key === card.dataset.childKey);
      const rows = card.querySelector('.child-rows');
      if (e.target.closest('.child-add')) {
        if (rows.children.length >= ch.max_rows) return toast.warn(`حداکثر ${ch.max_rows} ردیف مجاز است`);
        const empty = {}; ch.fields.forEach((f) => { empty[f.name] = f.i18n ? {} : (f.is_list ? [] : (f.kind === 'bool' ? false : '')); });
        rows.insertAdjacentHTML('beforeend', rowHtml(ch, empty, rows.children.length));
        setLang(form, activeLang); renumber(card); initDates(rows.lastElementChild);
      }
      const row = e.target.closest('.repeater-row');
      if (!row) return;
      if (e.target.closest('.row-del')) { row.remove(); renumber(card); }
      else if (e.target.closest('.row-up') && row.previousElementSibling) { row.parentNode.insertBefore(row, row.previousElementSibling); renumber(card); }
      else if (e.target.closest('.row-down') && row.nextElementSibling) { row.parentNode.insertBefore(row.nextElementSibling, row); renumber(card); }
    });

    let after = 'stay';
    form.querySelectorAll('button[type=submit]').forEach((b) => b.addEventListener('click', () => { after = b.dataset.after; }));

    // unsaved-changes guard + Ctrl/Cmd+S (handlers are replaced when the form is re-initialised after a save)
    let dirty = false;
    form.addEventListener('input', () => { dirty = true; });
    form.addEventListener('change', () => { dirty = true; });
    window.removeEventListener('beforeunload', Admin._guard);
    window.removeEventListener('keydown', Admin._ctrlS);
    Admin._guard = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
    Admin._ctrlS = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); after = 'stay'; if (!form.querySelector('button[type=submit]:disabled')) form.requestSubmit(); }
    };
    window.addEventListener('beforeunload', Admin._guard);
    window.addEventListener('keydown', Admin._ctrlS);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      showErrors(form, {});
      const btns = form.querySelectorAll('button[type=submit]');
      btns.forEach((b) => (b.disabled = true));
      try {
        const data = collect(form);
        const res = settings ? await api.put(apiBase, data) : (mode === 'edit' ? await api.put(`${apiBase}/${entityId}`, data) : await api.post(apiBase, data));
        toast.ok(`${ent.label} ذخیره شد`);
        dirty = false;
        if (settings) initForm();
        else if (after === 'close') location.href = pageBase;
        else if (mode === 'create') location.href = `${pageBase}/${res.id}/edit`;
        else { /* keep the page, refresh server-normalised values (slugs etc.) */ initForm(); }
      } catch (err) {
        if (err instanceof Admin.ApiError && err.fields) { toast.err(err.message); showErrors(form, err.fields); }
        else if (err instanceof Admin.ApiError) toast.err(err.message);
        else { console.error(err); toast.err('خطای غیرمنتظره'); }
      } finally {
        btns.forEach((b) => (b.disabled = false));
      }
    });

    form.querySelector('#btn-del')?.addEventListener('click', async () => {
      if (!(await Admin.confirm(`این ${ent.label} حذف شود؟ این کار قابل بازگشت نیست.`))) return;
      if (await safe(() => api.del(`${apiBase}/${entityId}`))) { dirty = false; toast.ok(`${ent.label} حذف شد`); location.href = pageBase; }
    });
  }

  (mode === 'list' ? initList() : initForm()).catch((e) => {
    root.innerHTML = `<div class="alert alert-danger">${esc(e.message || 'خطا در بارگذاری')}</div>`;
  });
})();
