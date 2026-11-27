// A one-off sign-in link (POST /api/auth/login-link): /login-link#<token>. The token is only
// ever in the fragment, which the browser doesn't send; it is removed from the address bar at
// once, exchanged for a session (kept in sessionStorage, as a password sign-in is), and the page
// moves on to where the link was made for.
'use strict';

(async () => {
  const token = decodeURIComponent((location.hash || '').replace(/^#/, ''));
  history.replaceState(null, '', location.pathname);
  const say = (t) => { document.getElementById('link-message').textContent = t; };
  if (!token) { say('This link has no sign-in code. Sign in with your password instead.'); return; }
  try {
    const res = await fetch('/api/auth/login-link/exchange', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { say((data && data.detail) || 'This sign-in link isn’t valid any more.'); return; }
    try { sessionStorage.setItem('ne_token', data.token); } catch { say('This browser won’t keep the sign-in (private mode?).'); return; }
    const next = typeof data.next === 'string' && data.next.startsWith('/') && !data.next.startsWith('//') ? data.next : '/';
    location.replace(next);
  } catch (e) {
    say('Couldn’t reach the service: ' + e.message);
  }
})();
