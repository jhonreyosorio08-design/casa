const toggle = document.getElementById('menu-toggle');
const mobile = document.getElementById('mobile-links');
if (toggle && mobile) toggle.addEventListener('click', () => mobile.classList.toggle('hidden'));

const loginModal = document.getElementById('login-modal');
document.querySelectorAll('.js-open-login').forEach(button => {
  button.addEventListener('click', () => {
    mobile?.classList.add('hidden');
    if (loginModal && !loginModal.open) loginModal.showModal();
    document.getElementById('modal-username')?.focus();
  });
});
document.querySelectorAll('.js-close-login').forEach(button => {
  button.addEventListener('click', () => loginModal?.close());
});
loginModal?.addEventListener('click', event => {
  if (event.target === loginModal) loginModal.close();
});

const notificationMenus = [...document.querySelectorAll('[data-notifications-url]')];
if (notificationMenus.length) {
  const safeHref = value => {
    try {
      const url = new URL(value, window.location.origin);
      return url.origin === window.location.origin ? url.href : window.location.origin;
    } catch { return window.location.origin; }
  };

  const refreshNotifications = async () => {
    const endpoint = notificationMenus[0].dataset.notificationsUrl;
    if (!endpoint) return;
    try {
      const response = await fetch(endpoint, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (!response.ok) return;
      const data = await response.json();
      notificationMenus.forEach(menu => {
        const badge = menu.querySelector('[data-notification-badge]');
        const count = Number(data.count) || 0;
        if (badge) {
          badge.textContent = count > 99 ? '99+' : String(count);
          badge.classList.toggle('is-empty', count === 0);
          menu.querySelector('summary')?.setAttribute('aria-label', count ? `Notifications, ${count} unread` : 'Notifications');
        }
        const countLabel = menu.querySelector('[data-notification-count]');
        if (countLabel) countLabel.textContent = `${count} unread`;
        const list = menu.querySelector('[data-notification-items]');
        if (!list) return;
        list.replaceChildren();
        if (!Array.isArray(data.items) || data.items.length === 0) {
          const empty = document.createElement('p');
          empty.className = 'notification-empty';
          empty.textContent = "You're all caught up.";
          list.append(empty);
          return;
        }
        data.items.forEach(item => {
          const link = document.createElement('a');
          link.className = 'notification-item';
          link.href = safeHref(item.url);
          const kind = document.createElement('span');
          kind.className = 'notification-kind';
          kind.textContent = item.kind || 'Notification';
          const message = document.createElement('span');
          message.className = 'notification-message';
          message.textContent = item.message || '';
          const date = document.createElement('time');
          date.textContent = item.date || '';
          link.append(kind, message, date);
          list.append(link);
        });
      });
      document.querySelectorAll('.notification-footer').forEach(link => { link.href = safeHref(data.footer_url); });
    } catch { /* Keep the server-rendered notifications if refresh fails. */ }
  };
  window.setInterval(refreshNotifications, 30000);
}
