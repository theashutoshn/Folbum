'use strict';

const $ = id => document.getElementById(id);
let status = null;
let preview = null;
let loading = false;
let syncing = false;
let draftInterval = null;
let savingSettings = false;
let retrievingSource = false;
let sourcePreviewFailed = false;
let sources = [];
let connectionActionBusy = false;
let reconnecting = false;
let lastDashboardRefresh = 0;
const DASHBOARD_REFRESH_MS = 60_000;

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
  const action = item.status === 'create' ? 'New album' : item.rename_pending ? 'Rename on sync' : item.missing ? `${item.missing} to add` : 'Up to date';
  line.append(info, element('span', item.status === 'create' ? 'new-label' : 'row-label', action));
  const rename = element('button', 'text-button album-rename');
  rename.type = 'button';
  rename.title = 'Rename ' + item.album;
  rename.setAttribute('aria-label', rename.title);
  const root = preview.configuration.root;
  rename.addEventListener('click', async () => {
    if (loading || syncing || savingSettings) return;
    const name = window.prompt('New album name', item.album)?.trim();
    if (!name || name === item.album) return;
    savingSettings = true;
    renderSchedule();
    rename.disabled = true;
    try {
      const result = await api('albums/rename', {method: 'POST', body: JSON.stringify({
        root, folder: item.folder, album_id: item.album_id, name
      })});
      notice(result.planned ? 'Album name saved for sync' : 'Album renamed');
      await load();
    } catch (error) {
      notice(error.message);
    } finally { savingSettings = false; rename.disabled = false; renderSchedule(); }
  });
  line.append(rename);
  return line;
}

function renderSources() {
  const list = $('sourceList');
  list.replaceChildren();
  if (!sources.length) {
    const message = !status?.connected ?
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
      if (savingSettings || loading) return;
      list.querySelectorAll('.source-option').forEach(option => option.classList.remove('selected'));
      card.classList.add('selected');
      $('root').value = source.path;
      retrievingSource = true;
      sourcePreviewFailed = false;
      preview = null;
      $('settingsHint').textContent = 'Retrieving';
      $('changeRows').replaceChildren();
      $('previewIntro').textContent = 'Retrieving albums…';
      $('sync').disabled = true;
      saveSettings({root: source.path});
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
      const count = preview.source_count ?? 0;
      meta.append(element('span', 'source-count', `${count.toLocaleString()} indexed media`));
    }
    details.append(meta);
    card.append(input, folder, details);
    list.append(card);
  }
}

function canSync() {
  return Boolean(status?.configuration.root && preview?.rows?.length && status.connected);
}

function renderConnection() {
  const hasNas = Boolean(status?.url);
  $('connectionEmpty').hidden = hasNas;
  $('connectionSummary').hidden = !hasNas;
  $('connectionEmpty').textContent = 'No NAS connected yet. Use + to add one.';
  $('addNas').title = 'Add NAS connection';
  if (!hasNas) return;
  $('nasName').textContent = status.name || 'ZimaOS NAS';
  $('nasAddress').textContent = status.url;
  const health = $('nasHealth');
  const disconnected = status.active === false;
  health.classList.toggle('healthy', !reconnecting && !disconnected && status.health === true);
  health.classList.toggle('unhealthy', !reconnecting && !disconnected && status.health === false);
  health.classList.toggle('disconnected', !reconnecting && disconnected);
  $('nasHealthLabel').textContent = reconnecting ? 'Connecting…' : disconnected ? 'Disconnected' :
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
  if (!status?.url || status.active === false) return;
  const url = status.url;
  status.health = undefined;
  renderConnection();
  try { await api('sources'); if (status.url === url) status.health = true; }
  catch (error) { if (status.url === url) status.health = false; }
  renderConnection();
}

const collapsedFolders = new Set();

function folderIcon(isSource) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', isSource
    ? 'M3 12l4-7h10l4 7v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1zm0 0h18M7 15h1m3 0h1'
    : 'M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1zm0 3h18');
  svg.append(path);
  return svg;
}

function renderFolderTree(folders) {
  const selection = preview?.configuration?.selected_folders;
  $('folderSettings').hidden = !folders.length || retrievingSource;
  $('allFolders').checked = selection == null;
  const tree = $('folderChoices');
  tree.replaceChildren();
  if (!folders.length) return;

  const source = preview.configuration.root;
  const root = {name: source.split('/').filter(Boolean).pop() || source, children: new Map(), count: 0};
  const selected = new Set(selection ?? folders);
  for (const folder of folders) {
    const count = preview.folder_counts?.[folder];
    let node = root;
    node.count += count ?? 0;
    for (const part of folder === '.' ? [] : folder.split('/')) {
      if (!node.children.has(part)) node.children.set(part, {name: part, children: new Map(), count: 0});
      node = node.children.get(part);
      node.count += count ?? 0;
    }
    node.folder = folder;
    node.directCount = count;
  }

  function appendFolder(parent, node, path, directOnly = false) {
    const branch = node.children.size > 0 || node === root;
    const row = element(branch && !directOnly ? 'button' : 'label', 'tree-row');
    const name = directOnly ? 'Files directly in this folder' : node.name;
    const group = element('div', 'tree-children');
    if (branch && !directOnly) {
      row.type = 'button';
      const key = JSON.stringify([source, path]);
      group.hidden = collapsedFolders.has(key);
      row.setAttribute('aria-expanded', String(!group.hidden));
      row.addEventListener('click', () => {
        group.hidden = !group.hidden;
        if (group.hidden) collapsedFolders.add(key);
        else collapsedFolders.delete(key);
        row.setAttribute('aria-expanded', String(!group.hidden));
      });
      row.append(element('span', 'tree-chevron'));
    } else {
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = selected.has(node.folder);
      input.addEventListener('change', () => {
        const next = new Set(selected);
        if (input.checked) next.add(node.folder);
        else next.delete(node.folder);
        saveSettings({selected_folders: [...next]});
      });
      row.append(input);
    }
    row.append(folderIcon(node === root && !directOnly), element('span', 'tree-name', name));
    const count = directOnly ? node.directCount : node.count;
    if (preview.folder_counts) row.append(element('span', 'tree-count', count.toLocaleString()));
    parent.append(row);
    if (branch && !directOnly) {
      parent.append(group);
      if (node.folder !== undefined) appendFolder(group, node, path, true);
      for (const child of node.children.values()) appendFolder(group, child, [...path, child.name]);
    }
  }
  appendFolder(tree, root, []);
}

function render() {
  const rows = preview?.rows || [];
  const folders = preview?.folders || [];
  renderFolderTree(folders);
  const changes = rows.filter(item => item.status === 'create' || item.rename_pending || item.missing > 0);
  const hasSource = Boolean(status?.configuration.root && status.connected);
  const disk = preview?.disk_comparison;
  const diskReady = disk?.status === 'ready';
  $('mediaCount').textContent = hasSource ?
    (diskReady ? disk.disk_count : preview?.source_count ?? 0).toLocaleString() : '—';
  $('mediaCountHint').textContent = diskReady ? 'Media files in the mounted source' : 'Indexed in the selected source';
  $('albumCount').textContent = hasSource ? rows.filter(item => item.album_id).length.toLocaleString() : '—';
  $('addedCount').textContent = hasSource ? rows.reduce((total, item) => total + item.count - item.missing, 0).toLocaleString() : '—';
  $('dashboardIntro').textContent = hasSource ? `Showing indexed media from ${status.configuration.root}` :
    !status?.connected ? 'Connect your NAS in Connection to see your library summary.' :
      'Choose a Photos source in Sync to see your library summary.';
  $('sync').disabled = syncing || !canSync();
  renderSources();

  const visible = $('changeRows');
  visible.replaceChildren();
  if (retrievingSource) {
    $('previewIntro').textContent = 'Retrieving albums…';
  } else if (!status?.connected) {
    $('previewIntro').textContent = 'Connect the NAS to view albums.';
  } else if (sourcePreviewFailed) {
    $('previewIntro').textContent = 'Could not retrieve albums. Reload preview to try again.';
  } else if (!status?.configuration.root) {
    $('previewIntro').textContent = 'Select a source to see its albums.';
  } else if (!rows.length && folders.length) {
    $('previewIntro').textContent = 'Select folders to sync.';
  } else if (!rows.length) {
    $('previewIntro').textContent = 'No indexed media folders found in this source.';
  } else if (!changes.length) {
    $('previewIntro').textContent = `All ${rows.length} albums are up to date.`;
  } else {
    $('previewIntro').textContent = `${changes.length} folder${changes.length === 1 ? '' : 's'} have changes ready.`;
  }
  for (const item of rows) visible.append(row(item));
  $('settingsHint').textContent = retrievingSource ? 'Retrieving' : !status?.connected ?
    'Connect NAS to begin' : sourcePreviewFailed ? 'Could not retrieve albums' :
      status?.configuration.root ? 'Source saved' : 'Choose a Photos source to begin';
  const latest = status?.history?.[0];
  const lastTime = latest ? new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    timeZoneName: 'short'
  }).format(new Date(latest.time * 1000)) : '';
  $('lastRun').textContent = latest ?
    `Last sync ${lastTime} · ${latest.added} added` : 'No syncs yet';
}

function showPage() {
  const requested = location.hash.slice(1);
  const page = ['dashboard', 'sync-settings', 'connection', 'account-settings'].includes(requested) ? requested : 'dashboard';
  const selected = page;
  document.querySelectorAll('.view').forEach(view => { view.hidden = view.id !== selected; });
  document.querySelectorAll('.menu-link').forEach(link => {
    if (link.hash === `#${selected}`) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  $('viewTitle').textContent = selected === 'dashboard' ? 'Dashboard' : selected === 'sync-settings' ? 'Sync' :
    selected === 'connection' ? 'Connection' : 'Settings';
  $('content').scrollTop = 0;
}

function setRefreshState(active, silent = false) {
  loading = active;
  $('folderSettings').disabled = loading || savingSettings || syncing;
  $('sourceList').inert = active || savingSettings;
  $('refreshDashboard').classList.toggle('is-loading', active && !silent);
  $('refreshDashboard').disabled = active;
  $('refreshDashboard').setAttribute('aria-label', active ? 'Refreshing dashboard' : 'Refresh dashboard');
  $('refresh').disabled = active;
  $('dashboardRefreshStatus').textContent = active && !silent ? 'Refreshing…' : '';
  if (active && !silent) $('dashboard').setAttribute('aria-busy', 'true');
  else $('dashboard').removeAttribute('aria-busy');
}

function setSyncState(active) {
  syncing = active;
  $('folderSettings').disabled = loading || savingSettings || syncing;
  $('sync').classList.toggle('is-syncing', active);
  $('sync').disabled = active || !canSync();
  $('sync').setAttribute('aria-busy', String(active));
  $('syncLabel').textContent = active ? 'Syncing…' : 'Sync now';
}

async function load() {
  if (loading) return;
  setRefreshState(true);
  try {
    status = await api('status');
    $('connectionStatus').textContent = status.connected ? 'NAS connected' : 'NAS disconnected';
    $('nasStatusDot').classList.toggle('is-connected', status.connected);
    status.health = status.connected ? undefined : false;
    renderConnection();
    $('interval').value = draftInterval ?? status.configuration.interval_minutes;
    renderSchedule();
    $('root').value = status.configuration.root || '';
    if (status.connected) {
      try {
        const sourceResponse = await api('sources');
        sources = sourceResponse.items;
        status.health = true;
        renderConnection();
      } catch (error) {
        status.health = false;
        renderConnection();
        sources = [];
        preview = {rows: []};
        sourcePreviewFailed = Boolean(status.configuration.root);
        notice('Could not reach ZimaOS Photos: ' + error.message);
      }
      if (status.health !== false) {
        try {
          preview = await api('preview');
          sourcePreviewFailed = false;
        }
        catch (error) {
          preview = {rows: []};
          sourcePreviewFailed = Boolean(status.configuration.root);
          notice('Could not load album preview: ' + error.message);
        }
      }
    } else {
      sources = [];
      preview = {rows: []};
      sourcePreviewFailed = false;
    }
    retrievingSource = false;
    render();
    showPage();
    lastDashboardRefresh = Date.now();
  } catch (error) {
    retrievingSource = false;
    sourcePreviewFailed = Boolean(status?.configuration.root);
    $('settingsHint').textContent = sourcePreviewFailed ? 'Could not retrieve albums' : 'Choose a Photos source to begin';
    notice('Could not load: ' + error.message);
  }
  finally { setRefreshState(false); }
}

async function refreshDashboardData(silent = false) {
  if (loading || syncing || savingSettings || connectionActionBusy || !status) return;
  setRefreshState(true, silent);
  try {
    const nextStatus = await api('status');
    const nextPreview = nextStatus.connected && nextStatus.configuration.root ?
      await api('preview') : {rows: []};
    const previousStatus = status;
    status = nextStatus;
    status.health = status.connected && status.url === previousStatus.url ? previousStatus.health : false;
    preview = nextPreview;
    sourcePreviewFailed = false;
    if (nextPreview.configuration) status.configuration = nextPreview.configuration;
    $('connectionStatus').textContent = status.connected ? 'NAS connected' : 'NAS disconnected';
    $('nasStatusDot').classList.toggle('is-connected', status.connected);
    renderConnection();
    $('interval').value = draftInterval ?? status.configuration.interval_minutes;
    renderSchedule();
    $('root').value = status.configuration.root || '';
    render();
    lastDashboardRefresh = Date.now();
  } catch (error) { if (!silent) notice('Could not refresh dashboard: ' + error.message); }
  finally { setRefreshState(false); }
}

function refreshDashboardIfStale() {
  if (!document.hidden && !$('dashboard').hidden &&
      !document.querySelector('dialog[open]') &&
      Date.now() - lastDashboardRefresh >= DASHBOARD_REFRESH_MS) {
    refreshDashboardData(true);
  }
}

function renderSchedule() {
  $('folderSettings').disabled = loading || savingSettings || syncing;
  const manual = $('interval').value === '0';
  $('sync').hidden = !manual;
  $('saveSchedule').hidden = manual;
  $('saveSchedule').disabled = savingSettings || !status ||
    Number($('interval').value) === status.configuration.interval_minutes;
  $('sync').disabled = savingSettings || syncing || !canSync();
  $('interval').disabled = savingSettings;
  $('sourceList').inert = savingSettings || loading;
}

async function saveSettings(changes) {
  if (savingSettings) return;
  savingSettings = true;
  renderSchedule();
  try {
    const config = await api('config', {method: 'POST', body: JSON.stringify(changes)});
    status.configuration = config;
    if ('interval_minutes' in changes) draftInterval = null;
    await load();
    notice('Settings saved');
  } catch (error) {
    if ('interval_minutes' in changes) draftInterval = null;
    if ('root' in changes) {
      retrievingSource = false;
      sourcePreviewFailed = false;
    }
    notice('Could not save: ' + error.message);
    await load();
  }
  finally { savingSettings = false; renderSchedule(); }
}

$('allFolders').addEventListener('change', () => {
  saveSettings({selected_folders: $('allFolders').checked ? null : []});
});

$('interval').addEventListener('change', () => {
  draftInterval = $('interval').value;
  renderSchedule();
  if (draftInterval === '0' && status?.configuration.interval_minutes !== 0) {
    saveSettings({interval_minutes: 0});
  }
});
$('saveSchedule').addEventListener('click', () => {
  saveSettings({interval_minutes: Number($('interval').value)});
});
$('logout').addEventListener('click', async () => {
  try {
    await api('logout', {method: 'POST'});
    location.replace('/login');
  } catch (error) { notice('Could not sign out: ' + error.message); }
});
$('changePasswordForm').addEventListener('submit', async event => {
  event.preventDefault();
  const error = $('passwordChangeError');
  error.textContent = '';
  const current = $('currentAccountPassword').value;
  const next = $('newAccountPassword').value;
  if (next !== $('confirmAccountPassword').value) {
    error.textContent = 'New passwords do not match';
    return;
  }
  $('changePasswordButton').disabled = true;
  try {
    await api('account/password', {method: 'POST', body: JSON.stringify({current_password: current, new_password: next})});
    $('changePasswordForm').reset();
    sessionStorage.setItem('folbumLoginNotice', 'Password changed. Sign in again.');
    location.replace('/login');
  } catch (failure) {
    error.textContent = failure.message;
    $('currentAccountPassword').value = '';
    $('changePasswordButton').disabled = false;
  }
});
window.addEventListener('hashchange', () => {
  showPage();
  if (location.hash === '#connection') checkConnectionHealth();
  refreshDashboardIfStale();
});
$('refresh').addEventListener('click', () => { if (!syncing) load(); });
$('refreshDashboard').addEventListener('click', () => refreshDashboardData());
document.addEventListener('visibilitychange', refreshDashboardIfStale);
setInterval(refreshDashboardIfStale, DASHBOARD_REFRESH_MS);
$('addNas').addEventListener('click', () => {
  $('nasForm').reset();
  $('nasFormError').textContent = '';
  $('nasDialog').showModal();
  $('url').focus();
});
$('toggleNas').addEventListener('click', async () => {
  if (connectionActionBusy || !status?.url) return;
  const reconnect = status.active === false;
  reconnecting = reconnect;
  connectionActionBusy = true;
  renderConnection();
  try {
    await api(reconnect ? 'connection/reconnect' : 'connection/disconnect', {method: 'POST'});
    if (reconnect) {
      status.active = true;
      status.connected = true;
      status.health = true;
    }
    await load();
    notice(reconnect ? 'NAS connected' : 'NAS disconnected');
  } catch (error) { notice((reconnect ? 'Could not connect NAS: ' : 'Could not disconnect NAS: ') + error.message); }
  finally { reconnecting = false; connectionActionBusy = false; renderConnection(); }
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
  if (syncing || loading || savingSettings || !canSync()) return;
  setSyncState(true);
  let outcome = '';
  try {
    const result = await api('sync', {method: 'POST', body: JSON.stringify({confirm: 'SYNC'})});
    outcome = `Sync complete: ${result.created} albums created, ${result.added} media added`;
    await load();
  } catch (error) { outcome = 'Sync failed: ' + error.message; }
  finally {
    setSyncState(false);
    if (outcome) notice(outcome);
  }
});

load();
