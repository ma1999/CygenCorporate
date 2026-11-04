/* Media library picker (modal) used by `media` fields:  Admin.pickMedia(url => ...)  — browses /api/admin/media/browse, can upload. */
(function () {
  'use strict';
  const { api, esc, toast } = Admin;
  let modalEl, bsModal, onPick, state;

  function ensureModal() {
    if (modalEl) return;
    modalEl = document.createElement('div');
    modalEl.className = 'modal fade';
    modalEl.tabIndex = -1;
    modalEl.innerHTML = `<div class="modal-dialog modal-xl modal-dialog-scrollable"><div class="modal-content">
      <div class="modal-header"><h5 class="modal-title">انتخاب تصویر / فایل</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">
        <div class="d-flex flex-wrap gap-2 mb-3 align-items-center">
          <nav class="flex-grow-1" id="mp-crumbs"></nav>
          <input type="search" class="form-control" id="mp-q" placeholder="جستجو..." style="width:200px">
          <label class="btn btn-primary mb-0"><i class="ti ti-upload me-1"></i>آپلود<input type="file" id="mp-up" multiple hidden></label>
        </div>
        <div id="mp-body"><div class="text-center py-5"><div class="spinner-border"></div></div></div>
      </div></div></div>`;
    document.body.appendChild(modalEl);
    bsModal = new bootstrap.Modal(modalEl);
    let t;
    modalEl.querySelector('#mp-q').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value; load(); }, 300); });
    modalEl.querySelector('#mp-up').addEventListener('change', async (e) => {
      const fd = new FormData();
      fd.append('folder', state.folder);
      [...e.target.files].forEach((f) => fd.append('files', f));
      try { await api.post('/api/admin/images/upload', fd); toast.ok('آپلود شد'); load(); } catch (ex) { toast.err(ex.message); }
      e.target.value = '';
    });
  }

  async function load() {
    const body = modalEl.querySelector('#mp-body');
    let d;
    try { d = await api.get('/api/admin/media/browse' + api.qs({ folder: state.folder, q: state.q, per_page: 60 })); }
    catch (ex) { body.innerHTML = `<div class="alert alert-danger">${esc(ex.message)}</div>`; return; }
    const parts = state.folder ? state.folder.split('/') : [];
    modalEl.querySelector('#mp-crumbs').innerHTML = `<ol class="breadcrumb mb-0"><li class="breadcrumb-item"><a href="#" data-f="">uploads</a></li>${parts.map((p, i) => `<li class="breadcrumb-item"><a href="#" data-f="${esc(parts.slice(0, i + 1).join('/'))}">${esc(p)}</a></li>`).join('')}</ol>`;
    body.innerHTML = `<div class="row g-3">
      ${d.folders.map((f) => `<div class="col-6 col-md-3 col-lg-2"><a href="#" class="card h-100 text-center text-decoration-none" data-f="${esc(f.rel)}"><div class="card-body py-4"><i class="ti ti-folder fs-1 text-warning"></i><div class="small text-truncate">${esc(f.name)}</div></div></a></div>`).join('')}
      ${d.files.map((f) => `<div class="col-6 col-md-3 col-lg-2"><a href="#" class="card h-100 text-center text-decoration-none" data-u="${esc(f.url)}">
        ${f.is_image ? `<img src="${esc(f.url)}" class="card-img-top" style="height:100px;object-fit:cover" loading="lazy">` : `<div class="py-4"><i class="ti ti-file fs-1"></i></div>`}
        <div class="card-body p-2"><div class="small text-truncate" title="${esc(f.name)}">${esc(f.name)}</div></div></a></div>`).join('')}
      ${!d.folders.length && !d.files.length ? '<p class="text-muted text-center">موردی یافت نشد</p>' : ''}</div>`;
  }

  modalDelegates();
  function modalDelegates() {
    document.addEventListener('click', (e) => {
      if (!modalEl || !modalEl.contains(e.target)) return;
      const a = e.target.closest('[data-f],[data-u]');
      if (!a) return;
      e.preventDefault();
      if (a.dataset.u !== undefined && a.dataset.u !== '') { bsModal.hide(); if (onPick) onPick(a.dataset.u); }
      else if (a.dataset.f !== undefined) { state.folder = a.dataset.f; load(); }
    });
  }

  Admin.pickMedia = function (cb) {
    ensureModal();
    onPick = cb;
    state = { folder: state ? state.folder : '', q: '' };
    modalEl.querySelector('#mp-q').value = '';
    bsModal.show();
    load();
  };
})();
