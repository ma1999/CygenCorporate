/* Runs the page module named by #page-app[data-page] (registered in Admin.pages by pages-*.js). */
(function () {
  'use strict';
  const root = document.getElementById('page-app');
  if (!root) return;
  const fn = Admin.pages[root.dataset.page];
  const params = JSON.parse(root.dataset.params || '{}');
  Promise.resolve(fn ? fn(root, params) : Promise.reject(new Error('صفحه ناشناخته'))).catch((e) => {
    console.error(e);
    root.innerHTML = `<div class="alert alert-danger">${Admin.esc(e.message || 'خطا در بارگذاری')}</div>`;
  });
})();
