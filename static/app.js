'use strict';

const $ = id => document.getElementById(id);
let status = null;
let preview = null;

async function api(path, options = {}) {
  const response = await fetch('/api/' + path, {
    ...options,
    headers: {'Content-Type': 'application/json', ...(options.headers || {})}
  });
  const data = await response.json();
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

function render() {
  const rows = preview?.rows || [];
  const changes = rows.filter(item => item.status === 'create' || item.missing > 0);
  $('foldersCount').textContent = rows.length;
  $('newCount').textContent = rows.filter(item => item.status === 'create').length;
  $('pendingCount').textContent = rows.reduce((total, item) => total + (item.missing || 0), 0);
  $('settingsHint').textContent = status?.configuration.root ? 'Saved automatically' : 'Choose a Photos source to begin';
  $('actionHint').textContent = status?.mode === 'demo' ? 'Sample library' :
    status?.live_writes_enabled ? 'Creates albums and adds indexed media' : 'Live writes are disabled';
  $('sync').disabled = !status?.configuration.root || !rows.length ||
    (status.mode === 'live' && (!status.connected || !status.live_writes_enabled));

  const visible = $('changeRows');
  visible.replaceChildren();
  if (!status?.configuration.root) {
    $('previewIntro').textContent = 'Select a source to see what will happen.';
  } else if (!rows.length) {
    $('previewIntro').textContent = 'No indexed media folders found in this source.';
  } else if (!changes.length) {
    $('previewIntro').textContent = `All ${rows.length} albums are up to date.`;
  } else {
    $('previewIntro').textContent = `${changes.length} folder${changes.length === 1 ? '' : 's'} have changes ready.`;
    for (const item of changes.slice(0, 3)) visible.append(row(item));
  }

  const allPanel = $('allPanel');
  allPanel.hidden = rows.length === 0;
  $('allSummary').textContent = `View all ${rows.length} media folder${rows.length === 1 ? '' : 's'}`;
  const allRows = $('allRows');
  allRows.replaceChildren();
  for (const item of rows) allRows.append(row(item));
  const latest = status?.history?.[0];
  $('lastRun').textContent = latest ?
    `Last sync ${new Date(latest.time * 1000).toLocaleString()} · ${latest.added} added` : 'No syncs yet';
}

async function load() {
  try {
    status = await api('status');
    $('mode').textContent = status.mode === 'demo' ? 'Demo' : status.live_writes_enabled ? 'Live' : 'Read only';
    $('url').value = status.url || '';
    $('connectionPanel').hidden = status.mode === 'demo';
    $('connectionPanel').open = status.mode === 'live' && !status.connected;
    $('connectionStatus').textContent = status.connected ? status.url : 'Not connected';
    $('interval').value = status.configuration.interval_minutes;
    const selector = $('root');
    selector.replaceChildren();
    const prompt = element('option', '', 'Choose a source');
    prompt.value = '';
    selector.append(prompt);
    if (status.mode === 'demo' || status.connected) {
      const sources = await api('sources');
      for (const source of sources.items) {
        const option = element('option', '', source.path + (source.available ? '' : ' · unavailable'));
        option.value = source.path;
        option.disabled = !source.available;
        selector.append(option);
      }
      selector.value = status.configuration.root || '';
      preview = await api('preview');
    } else {
      preview = {rows: []};
    }
    render();
  } catch (error) { notice('Could not load: ' + error.message); }
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

$('root').addEventListener('change', saveSettings);
$('interval').addEventListener('change', saveSettings);
$('refresh').addEventListener('click', load);
$('connect').addEventListener('click', async () => {
  try {
    await api('connect', {method: 'POST', body: JSON.stringify({
      url: $('url').value.trim(), username: $('username').value.trim(), password: $('password').value
    })});
    $('password').value = '';
    notice('Connected to ZimaOS Photos');
    await load();
  } catch (error) { $('password').value = ''; notice('Connection failed: ' + error.message); }
});
$('sync').addEventListener('click', async () => {
  const count = preview?.rows?.length || 0;
  if (!confirm(`Sync ${count} media folder${count === 1 ? '' : 's'} to Photos albums?`)) return;
  try {
    const result = await api('sync', {method: 'POST', body: JSON.stringify({confirm: 'SYNC'})});
    notice(`Synced: ${result.created} albums created, ${result.added} media added`);
    await load();
  } catch (error) { notice('Sync failed: ' + error.message); }
});

load();
