'use strict';

const form = document.getElementById('loginForm');
const error = document.getElementById('loginError');
const button = document.getElementById('loginButton');

form.addEventListener('submit', async event => {
  event.preventDefault();
  error.textContent = '';
  button.disabled = true;
  button.textContent = 'Signing in…';
  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        username: document.getElementById('loginUsername').value.trim(),
        password: document.getElementById('loginPassword').value,
        remember: document.getElementById('rememberLogin').checked
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not sign in');
    location.replace('/app');
  } catch (failure) {
    error.textContent = failure.message;
    document.getElementById('loginPassword').value = '';
    document.getElementById('loginPassword').focus();
    button.disabled = false;
    button.textContent = 'Sign in';
  }
});
