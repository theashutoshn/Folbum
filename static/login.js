'use strict';

const form = document.getElementById('loginForm');
const error = document.getElementById('loginError');
const button = document.getElementById('loginButton');
const setupDialog = document.getElementById('setupDialog');
const setupForm = document.getElementById('setupForm');
const setupError = document.getElementById('setupError');
const setupButton = document.getElementById('setupButton');
const loginNotice = sessionStorage.getItem('folbumLoginNotice');
if (loginNotice) {
  document.getElementById('loginNotice').textContent = loginNotice;
  sessionStorage.removeItem('folbumLoginNotice');
}

async function checkSetup() {
  try {
    const response = await fetch('/api/setup/status');
    if (!response.ok) throw new Error('Could not check account setup');
    if ((await response.json()).required) {
      setupDialog.showModal();
      document.getElementById('setupUsername').focus();
    }
  } catch (failure) { error.textContent = failure.message; }
}

setupDialog.addEventListener('cancel', event => event.preventDefault());
setupForm.addEventListener('submit', async event => {
  event.preventDefault();
  setupError.textContent = '';
  const username = document.getElementById('setupUsername').value.trim();
  const password = document.getElementById('setupPassword').value;
  if (password !== document.getElementById('setupConfirm').value) {
    setupError.textContent = 'Passwords do not match';
    return;
  }
  setupButton.disabled = true;
  try {
    const response = await fetch('/api/setup', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username, password})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not create account');
    setupForm.reset();
    setupDialog.close();
    document.getElementById('loginUsername').value = username;
    error.textContent = 'Account created. Sign in with your new password.';
    document.getElementById('loginPassword').focus();
  } catch (failure) { setupError.textContent = failure.message; }
  finally { setupButton.disabled = false; }
});

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

checkSetup();
