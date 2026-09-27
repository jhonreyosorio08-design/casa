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
