const toggle = document.getElementById('menu-toggle');
const mobile = document.getElementById('mobile-links');
if (toggle && mobile) {
  const setMenuOpen = open => {
    mobile.classList.toggle('hidden', !open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  };
  toggle.addEventListener('click', () => setMenuOpen(toggle.getAttribute('aria-expanded') !== 'true'));
  mobile.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setMenuOpen(false)));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') setMenuOpen(false);
  });
}

const revealItems = document.querySelectorAll('[data-reveal]');
if (revealItems.length && 'IntersectionObserver' in window) {
  document.documentElement.classList.add('reveal-enabled');
  const revealObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('is-visible');
      revealObserver.unobserve(entry.target);
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -35px 0px' });
  revealItems.forEach(item => revealObserver.observe(item));
}

const typingPhrases = document.querySelectorAll('[data-typing-phrases]');
if (typingPhrases.length) {
  typingPhrases.forEach(element => {
    const phrases = (element.dataset.typingPhrases || '').split('|').filter(Boolean);
    if (!phrases.length) return;
    let phraseIndex = 0;
    let position = 0;
    let deleting = false;
    element.textContent = '';

    const typeNext = () => {
      const phrase = phrases[phraseIndex];
      if (deleting) {
        position = Math.max(0, position - 1);
        element.textContent = phrase.slice(0, position);
        if (position === 0) {
          deleting = false;
          phraseIndex = (phraseIndex + 1) % phrases.length;
          window.setTimeout(typeNext, 300);
          return;
        }
        window.setTimeout(typeNext, 38);
        return;
      }

      const nextPhrase = phrases[phraseIndex];
      position = Math.min(nextPhrase.length, position + 1);
      element.textContent = nextPhrase.slice(0, position);
      if (position === nextPhrase.length) {
        deleting = true;
        window.setTimeout(typeNext, 3200);
        return;
      }
      window.setTimeout(typeNext, 82);
    };

    window.setTimeout(typeNext, 400);
  });
}

const loginModal = document.getElementById('login-modal');
document.querySelectorAll('.js-open-login').forEach(button => {
  button.addEventListener('click', () => {
    mobile?.classList.add('hidden');
    toggle?.setAttribute('aria-expanded', 'false');
    toggle?.setAttribute('aria-label', 'Open menu');
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
const notificationModal = document.getElementById('notification-modal');
let lastNotificationTrigger = null;
document.addEventListener('click', event => {
  const trigger = event.target.closest('[data-notification-view]');
  if (!trigger || !notificationModal) return;
  lastNotificationTrigger = trigger;
  const title = document.getElementById('notification-modal-title');
  const message = document.getElementById('notification-modal-message');
  const thanks = document.getElementById('notification-modal-thanks');
  const body = trigger.dataset.message || '';
  const preparing = body.match(/Reservation\s+([A-Z0-9-]+)\s+is now preparing\.?/i);
  message.replaceChildren();
  if (preparing) {
    title.textContent = 'Your reservation is being prepared';
    const reservation = document.createElement('p');
    reservation.append('Reservation ');
    const reference = document.createElement('strong');
    reference.textContent = preparing[1];
    reservation.append(reference, ' has been accepted and is now being prepared by our team. We’ll notify you once everything is ready for your visit.');
    message.append(reservation);
    thanks.textContent = 'Thank you for choosing Casa Sonata. We look forward to welcoming you!';
  } else {
    title.textContent = trigger.dataset.title || 'Notification';
    const paragraph = document.createElement('p');
    paragraph.textContent = body;
    message.append(paragraph);
    thanks.textContent = 'Thank you for choosing Casa Sonata.';
  }
  trigger.closest('.notification-menu')?.removeAttribute('open');
  notificationModal.showModal();
  notificationModal.querySelector('[data-notification-modal-close]')?.focus();
});
notificationModal?.querySelectorAll('[data-notification-modal-close]').forEach(button => {
  button.addEventListener('click', () => notificationModal.close());
});
notificationModal?.addEventListener('click', event => {
  if (event.target === notificationModal) notificationModal.close();
});
notificationModal?.addEventListener('close', () => lastNotificationTrigger?.focus());

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
        const markAllForm = menu.querySelector('[data-mark-all-form]');
        if (markAllForm) markAllForm.hidden = count === 0;
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
          const button = document.createElement('button');
          button.type = 'button';
          button.className = `notification-item${item.is_read ? '' : ' is-unread'}`;
          button.dataset.notificationView = '';
          button.dataset.title = item.kind || 'Notification';
          button.dataset.message = item.message || '';
          button.dataset.date = item.date || '';
          button.dataset.read = String(Boolean(item.is_read));
          const kind = document.createElement('span');
          kind.className = 'notification-kind';
          kind.textContent = item.kind || 'Notification';
          const message = document.createElement('span');
          message.className = 'notification-message';
          message.textContent = item.message || '';
          const date = document.createElement('time');
          date.textContent = item.date || '';
          message.title = item.message || '';
          const view = document.createElement('span');
          view.className = 'notification-view-label';
          view.setAttribute('aria-hidden', 'true');
          view.textContent = 'View →';
          button.append(kind, message, date, view);
          list.append(button);
        });
      });
      document.querySelectorAll('.notification-footer').forEach(link => { link.href = safeHref(data.footer_url); });
    } catch { /* Keep the server-rendered notifications if refresh fails. */ }
  };
  window.setInterval(refreshNotifications, 30000);
}
