/* Shared behaviour of every panel page: logout. (Menu/user are rendered by the shell; the same data is on GET /api/admin/auth/me.) */
(function () {
  'use strict';
  const btn = document.getElementById('btn-logout');
  if (btn) {
    btn.addEventListener('click', async () => {
      await Admin.safe(() => Admin.api.post('/api/admin/auth/logout', {}, { noRedirect: true }));
      location.href = '/login';
    });
  }
})();
