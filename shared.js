window.miellLogout = async function () {
  const token = localStorage.getItem('dochadzka_token');
  try {
    if (token) {
      const response = await fetch('/api/auth/logout', {method:'POST', headers:{Authorization:'Bearer '+token}});
      if (!response.ok && response.status !== 401) throw new Error('Odhlásenie sa nepodarilo. Skús znova.');
    }
    localStorage.removeItem('dochadzka_token');
    location.href='/';
  } catch (error) { alert(error.message || 'Server nie je dostupný. Skús odhlásenie znova.'); }
};
window.addEventListener('storage', event => {
  if(event.key==='dochadzka_token' && !event.newValue)location.replace('/');
});
