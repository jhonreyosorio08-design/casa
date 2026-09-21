const toggle = document.getElementById('menu-toggle');
const mobile = document.getElementById('mobile-links');
if (toggle && mobile) toggle.addEventListener('click', () => mobile.classList.toggle('hidden'));
