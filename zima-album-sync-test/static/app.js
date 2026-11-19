'use strict';

const $ = id => document.getElementById(id);
let status = null;
let preview = null;
let loading = false;
let syncing = false;
let sources = [];
let connectionActionBusy = false;

async function api(path, options = {}) {
  const response = await fetch('/api/' + path, {
    ...options,
    headers: {'Content-Type': 'application/json', ...(options.headers || {})}
  });
  const data = await response.json();
  if (response.status === 401) {
    location.replace('/login');
    throw new Error('Session expired');
  }
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}

function notice(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.add('visible');
  clearTimeout(notice.timer);
  notice.timer = setTimeout(() => toast.classList.remove('visible'), 5000);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function row(item) {
  const line = element('div', 'album-row');
  const info = element('div', 'album-info');
  info.append(element('strong', '', item.album), element('span', '', item.folder === '.' ? 'Source root' : item.folder));
  const action = item.status === 'create' ? 'New album' : item.missing ? `${item.missing} to add` : 'Up to date';
  line.append(info, element('span', item.status === 'create' ? 'new-label' : 'row-label', action));
  return line;
}

function renderSources() {
  const list = $('sourceList');
  list.replaceChildren();
  if (!sources.length) {
    const message = status?.mode === 'live' && !status.connected ?
      'Connect to ZimaOS Photos to see available sources.' :
      'No Photos sources available. Add one in ZimaOS Photos, then reload the preview.';
    list.append(element('p', 'source-empty', message));
    return;
  }
  for (const source of sources) {
    const card = element('label', 'source-option');
    const input = element('input');
    input.type = 'radio';
    input.name = 'photosSource';
    input.value = source.path;
    input.checked = source.path === status.configuration.root;
    input.disabled = !source.available;
    input.addEventListener('change', () => {
      list.querySelectorAll('.source-option').forEach(option => option.classList.remove('selected'));
      card.classList.add('selected');
      $('root').value = source.path;
      saveSettings();
    });
    if (input.checked) card.classList.add('selected');
    if (!source.available) card.classList.add('unavailable');
    const folder = element('span', 'source-folder');
    folder.setAttribute('aria-hidden', 'true');
    const details = element('span', 'source-details');
    details.append(element('strong', 'source-path', source.path));
    const meta = element('span', 'source-meta');
    const stateLabel = source.available ? (source.status === 'normal' ? 'Normal' : 'Available') : 'Unavailable';
    const state = element('span', 'source-state', stateLabel);
    meta.append(state);
    if (input.checked && preview?.rows) {
      const count = preview.rows.reduce((total, item) => total + item.count, 0);
      meta.append(element('span', 'source-count', `${count.toLocaleString()} indexed media`));
    }
    details.append(meta);
    card.append(input, folder, details);
    list.append(card);
  }
}

function canSync() {
  return Boolean(status?.configuration.root && preview?.rows?.length &&
    (status.mode !== 'live' || (status.connected && status.live_writes_enabled)));
}

function renderConnection() {
  const hasNas = status?.mode === 'live' && Boolean(status.url);
  $('connectionEmpty').hidden = hasNas;
  $('connectionSummary').hidden = !hasNas;
  $('connectionEmpty').textContent = status?.mode === 'demo' ?
    'Demo mode uses sample media. Set ZIMA_MODE=live and restart the app to connect a NAS.' :
    'No NAS connected yet. Use + to add one.';
  $('addNas').disabled = status?.mode !== 'live';
  $('addNas').title = status?.mode === 'demo' ? 'Available in live mode' : 'Add NAS connection';
  if (!hasNas) return;
  $('nasName').textContent = status.name || 'ZimaOS NAS';
  $('nasAddress').textContent = status.url;
  const health = $('nasHealth');
  const disconnected = status.active === false;
  health.classList.toggle('healthy', !disconnected && status.health === true);
  health.classList.toggle('unhealthy', !disconnected && status.health === false);
  health.classList.toggle('disconnected', disconnected);
  $('nasHealthLabel').textContent = disconnected ? 'Disconnected' :
    status.health === true ? 'Healthy' : status.health === false ? 'Unhealthy' : 'Checking…';
  $('disconnectIcon').hidden = disconnected;
  $('reconnectIcon').hidden = !disconnected;
  $('toggleNas').classList.toggle('disconnect-action', !disconnected);
  $('toggleNas').classList.toggle('reconnect-action', disconnected);
  $('toggleNas').setAttribute('aria-label', disconnected ? 'Connect NAS' : 'Disconnect NAS');
  $('toggleNas').title = disconnected ? 'Connect NAS' : 'Disconnect NAS';
  $('toggleNas').disabled = connectionActionBusy;
  $('deleteNas').disabled = connectionActionBusy;
}

async function checkConnectionHealth() {
  if (status?.mode !== 'live' || !status.url || status.active === false) return;
  const url = status.url;
  status.health = undefined;
  renderConnection();
  try { await api('sources'); if (status.url === url) status.health = true; }
  catch (error) { if (status.url === url) status.health = false; }
  renderConnection();
}

function render() {
  const rows = preview?.rows || [];
  const changes = rows.filter(item => item.status === 'create' || item.missing > 0);
  const hasSource = Boolean(status?.configuration.root &&
    (status.mode !== 'live' || status.connected));
  const disk = preview?.disk_comparison;
  const diskReady = disk?.status === 'ready';
  $('mediaCount').textContent = hasSource ?
    (diskReady ? disk.disk_count : rows.reduce((total, item) => total + item.count, 0)).toLocaleString() : '—';
  $('mediaCountHint').textContent = diskReady ? 'Media files in the mounted source' : 'Indexed in the selected source';
  $('albumCount').textContent = hasSource ? rows.filter(item => item.album_id).length.toLocaleString() : '—';
  $('addedCount').textContent = hasSource ? rows.reduce((total, item) => total + item.count - item.missing, 0).toLocaleString() : '—';
  $('dashboardIntro').textContent = hasSource ? `Showing indexed media from ${status.configuration.root}` :
    'Choose a Photos source in Sync settings to see your library summary.';
  $('settingsHint').textContent = status?.configuration.root ? 'Saved automatically' : 'Choose a Photos source to begin';
  $('actionHint').textContent = syncing ? 'Sync in progress…' : status?.mode === 'demo' ? 'Sample library' :
    status?.live_writes_enabled ? 'Creates albums and adds indexed media' : 'Live writes are disabled';
  $('sync').disabled = syncing || !canSync();
  renderSources();

  const visible = $('changeRows');
  visible.replaceChildren();
  if (status?.mode === 'live' && !status.connected) {
    $('previewIntro').textContent = 'Connect the NAS to view albums.';
  } else if (!status?.configuration.root) {
    $('previewIntro').textContent = 'Select a source to see its albums.';
  } else if (!rows.length) {
    $('previewIntro').textContent = 'No indexed media folders found in this source.';
  } else if (!changes.length) {
    $('previewIntro').textContent = `All ${rows.length} albums are up to date.`;
  } else {
    $('previewIntro').textContent = `${changes.length} folder${changes.length === 1 ? '' : 's'} have changes ready.`;
  }
  for (const item of rows) visible.append(row(item));
  const latest = status?.history?.[0];
  const lastTime = latest ? new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    timeZone: status.timezone || undefined, timeZoneName: 'short'
  }).format(new Date(latest.time * 1000)) : '';
  $('lastRun').textContent = latest ?
    `Last sync ${lastTime} · ${latest.added} added` : 'No syncs yet';
}

function showPage() {
  const requested = location.hash.slice(1);
  const page = ['dashboard', 'sync-settings', 'connection'].includes(requested) ? requested : 'dashboard';
  const selected = page;
  document.querySelectorAll('.view').forEach(view => { view.hidden = view.id !== selected; });
  document.querySelectorAll('.menu-link').forEach(link => {
    if (link.hash === `#${selected}`) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  $('viewTitle').textContent = selected === 'dashboard' ? 'Dashboard' : selected === 'sync-settings' ? 'Sync settings' : 'Connection';
  $('content').scrollTop = 0;
}

function setRefreshState(active) {
  loading = active;
  $('refreshDashboard').classList.toggle('is-loading', active);
  $('refreshDashboard').disabled = active;
  $('refreshDashboard').setAttribute('aria-label', active ? 'Refreshing dashboard' : 'Refresh dashboard');
  $('refresh').disabled = active;
  $('dashboardRefreshStatus').textContent = active ? 'Refreshing…' : '';
  if (active) $('dashboard').setAttribute('aria-busy', 'true');
  else $('dashboard').removeAttribute('aria-busy');
}

function setSyncState(active) {
  syncing = active;
  $('sync').classList.toggle('is-syncing', active);
  $('sync').disabled = active || !canSync();
  $('sync').setAttribute('aria-busy', String(active));
  $('syncLabel').textContent = active ? 'Syncing…' : 'Sync now';
  if (active) $('actionHint').textContent = 'Sync in progress…';
}

async function load() {
  if (loading) return;
  setRefreshState(true);
  try {
    status = await api('status');
    $('mode').textContent = status.mode === 'demo' ? 'Demo' : status.live_writes_enabled ? 'Live' : 'Read only';
    status.health = status.mode === 'live' && status.connected ? undefined : false;
    renderConnection();
    $('interval').value = status.configuration.interval_minutes;
    $('root').value = status.configuration.root || '';
    if (status.mode === 'demo' || status.connected) {
      try {
        const sourceResponse = await api('sources');
        sources = sourceResponse.items;
        status.health = status.mode === 'live' ? true : undefined;
        renderConnection();
      } catch (error) {
        status.health = false;
        renderConnection();
        sources = [];
        preview = {rows: []};
        notice('Could not reach ZimaOS Photos: ' + error.message);
      }
      if (status.health !== false) {
        try { preview = await api('preview'); }
        catch (error) {
          preview = {rows: []};
          notice('Could not load album preview: ' + error.message);
        }
      }
    } else {
      sources = [];
      preview = {rows: []};
    }
    render();
    showPage();
  } catch (error) { notice('Could not load: ' + error.message); }
  finally { setRefreshState(false); }
}

async function refreshDashboardData() {
  if (loading || syncing || !status) return;
  setRefreshState(true);
  try {
    const [nextPreview, history] = await Promise.all([api('preview'), api('history')]);
    preview = nextPreview;
    status.configuration = nextPreview.configuration;
    status.history = history.slice(0, 10);
    $('root').value = status.configuration.root || '';
    render();
  } catch (error) { notice('Could not refresh dashboard: ' + error.message); }
  finally { setRefreshState(false); }
}

async function saveSettings() {
  try {
    await api('config', {method: 'POST', body: JSON.stringify({
      root: $('root').value, interval_minutes: Number($('interval').value)
    })});
    await load();
    notice('Settings saved');
  } catch (error) { notice('Could not save: ' + error.message); await load(); }
}

$('interval').addEventListener('change', saveSettings);
$('logout').addEventListener('click', async () => {
  try {
    await api('logout', {method: 'POST'});
    location.replace('/login');
  } catch (error) { notice('Could not sign out: ' + error.message); }
});
window.addEventListener('hashchange', () => {
  showPage();
  if (location.hash === '#connection') checkConnectionHealth();
});
$('refresh').addEventListener('click', () => { if (!syncing) load(); });
$('refreshDashboard').addEventListener('click', refreshDashboardData);
$('addNas').addEventListener('click', () => {
  $('nasForm').reset();
  $('nasFormError').textContent = '';
  $('nasDialog').showModal();
  $('url').focus();
});
$('toggleNas').addEventListener('click', async () => {
  if (connectionActionBusy || !status?.url) return;
  const reconnect = status.active === false;
  connectionActionBusy = true;
  renderConnection();
  try {
    await api(reconnect ? 'connection/reconnect' : 'connection/disconnect', {method: 'POST'});
    await load();
    notice(reconnect ? 'NAS connected' : 'NAS disconnected');
  } catch (error) { notice((reconnect ? 'Could not connect NAS: ' : 'Could not disconnect NAS: ') + error.message); }
  finally { connectionActionBusy = false; renderConnection(); }
});
$('deleteNas').addEventListener('click', async () => {
  if (connectionActionBusy || !status?.url) return;
  connectionActionBusy = true;
  renderConnection();
  try {
    await api('connection/delete', {method: 'POST'});
    await load();
    notice('NAS entry deleted');
  } catch (error) { notice('Could not delete NAS entry: ' + error.message); }
  finally { connectionActionBusy = false; renderConnection(); }
});
$('closeNasDialog').addEventListener('click', () => $('nasDialog').close());
$('cancelNas').addEventListener('click', () => $('nasDialog').close());
$('nasDialog').addEventListener('close', () => { $('password').value = ''; });
$('nasForm').addEventListener('submit', async event => {
  event.preventDefault();
  if ($('connect').disabled) return;
  $('connect').disabled = true;
  $('connect').textContent = 'Connecting…';
  $('nasFormError').textContent = '';
  try {
    await api('connect', {method: 'POST', body: JSON.stringify({
      url: $('url').value.trim(), name: $('nasAlias').value.trim(),
      username: $('username').value.trim(), password: $('password').value,
      remember_connection: $('rememberConnection').checked
    })});
    $('nasDialog').close();
    notice('Connected to ZimaOS Photos');
    await load();
  } catch (error) {
    $('password').value = '';
    $('nasFormError').textContent = error.message;
  } finally {
    $('connect').disabled = false;
    $('connect').textContent = 'Connect NAS';
  }
});
$('sync').addEventListener('click', async () => {
  if (syncing || loading || !canSync()) return;
  setSyncState(true);
  let outcome = '';
  try {
    const result = await api('sync', {method: 'POST', body: JSON.stringify({confirm: 'SYNC'})});
    outcome = `Sync complete: ${result.created} albums created, ${result.added} media added`;
    await load();
  } catch (error) { outcome = 'Sync failed: ' + error.message; }
  finally {
    setSyncState(false);
    $('actionHint').textContent = outcome;
    if (outcome) notice(outcome);
  }
});

load();
