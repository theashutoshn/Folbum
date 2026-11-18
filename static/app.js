'use strict';
const $ = id => document.getElementById(id);
let cfg = null, tree = [], status = null;
async function api(path, options = {}) {
  const response = await fetch('/api/' + path, {...options, headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function toast(message) {
  $('toast').textContent = message;
  $('toast').style.display = 'block';
  setTimeout(() => $('toast').style.display = 'none', 4800);
}
function el(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}
function populate() {
  $('naming').value = cfg.naming;
  $('interval').value = cfg.interval_minutes;
  const list = $('folders');
  list.replaceChildren();
  for (const item of tree) {
    const row = el('div', 'folderrow');
    const left = el('div', 'foldername');
    left.style.paddingLeft = Math.min(item.depth * 20, 120) + 'px';
    const enabled = el('input', 'enabled');
    enabled.type = 'checkbox';
    enabled.dataset.folder = item.path;
    enabled.checked = !!cfg.rules[item.path]?.enabled;
    const label = el('span', 'folderlabel', item.path.split('/').pop());
    label.title = item.path;
    left.append(enabled, label, el('span', 'foldermeta', item.count + ' direct'));
    const recursive = el('input', 'recursive');
    recursive.type = 'checkbox';
    recursive.title = 'Include nested folders';
    recursive.checked = !!cfg.rules[item.path]?.recursive;
    const override = el('input', 'smallinput');
    override.type = 'text';
    override.placeholder = 'Automatic name';
    override.maxLength = 150;
    override.value = cfg.rules[item.path]?.name || '';
    row.append(left, recursive, override);
    list.append(row);
  }
}
function collect() {
  const rules = {...cfg.rules};
  for (const row of $('folders').children) {
    const folder = row.querySelector('.enabled').dataset.folder;
    rules[folder] = {enabled: row.querySelector('.enabled').checked,
      recursive: row.querySelector('.recursive').checked,
      name: row.querySelector('.smallinput').value.trim()};
  }
  return {root: $('root').value, naming: $('naming').value,
    interval_minutes: Number($('interval').value), rules};
}
async function load() {
  try {
    status = await api('status');
    cfg = status.configuration;
    $('mode').textContent = status.mode;
    $('url').value = status.url || '';
    $('connection').hidden = status.mode === 'demo';
    $('connectionStatus').textContent = status.connected ? 'Connected to ' + status.url : 'Not connected';
    if (status.mode === 'live' && !status.connected) {
      tree = []; populate(); render({tree: [], rows: [], asset_count: 0, album_count: 0});
      return;
    }
    const sources = await api('sources');
    const selector = $('root');
    selector.replaceChildren(el('option', '', 'Choose a source'));
    selector.firstChild.value = '';
    for (const source of sources.items) {
      const option = el('option', '', source.path + (source.available ? '' : ' (unavailable)'));
      option.value = source.path;
      option.disabled = !source.available;
      selector.append(option);
    }
    selector.value = cfg.root || '';
    const preview = await api('preview');
    tree = preview.tree;
    populate();
    render(preview);
  } catch (error) { toast('Error: ' + error.message); }
}
function render(preview) {
  $('assets').textContent = preview.asset_count;
  $('albums').textContent = preview.album_count;
  $('selected').textContent = Object.values(cfg.rules).filter(rule => rule.enabled).length;
  $('pending').textContent = preview.rows.reduce((sum, row) => sum + (row.missing || 0), 0);
  $('writeFlag').textContent = status.mode === 'demo' ? 'Demo mode' : status.live_writes_enabled ? 'Live mode' : 'Read only';
  $('actionHint').textContent = status.mode === 'demo' ? 'Uses sample data' : status.live_writes_enabled ? 'Creates albums and adds indexed assets' : 'Live writes disabled';
  $('sync').disabled = status.mode === 'live' && (!status.live_writes_enabled || !status.connected);
  const results = $('results');
  results.replaceChildren();
  if (!preview.rows.length) results.append(el('p', '', 'Choose a source, then select and save folders to preview changes.'));
  for (const row of preview.rows) {
    const line = el('div', 'result');
    const left = el('div');
    left.append(el('b', '', row.album), el('div', 'foldermeta', row.folder));
    const message = row.status === 'not-indexed' ? 'Not indexed' : row.status === 'create' ?
      `Create album with ${row.missing} assets` : `${row.missing} new of ${row.count} assets`;
    line.append(left, el('span', row.status === 'create' ? 'create' : 'existing', message));
    results.append(line);
  }
  const history = $('history');
  history.replaceChildren();
  if (!status.history.length) history.append(el('span', '', 'No runs yet.'));
  for (const run of status.history) history.append(el('div', '',
    `${new Date(run.time * 1000).toLocaleString()} - ${run.created} albums created - ${run.added} assets added`));
}
async function save() {
  try { cfg = await api('config', {method: 'POST', body: JSON.stringify(collect())}); toast('Settings saved'); await load(); }
  catch (error) { toast('Error: ' + error.message); }
}
$('connect').addEventListener('click', async () => {
  try {
    await api('connect', {method: 'POST', body: JSON.stringify({url: $('url').value.trim(),
      username: $('username').value.trim(), password: $('password').value})});
    $('password').value = '';
    toast('Connected to ZimaOS Photos');
    await load();
  } catch (error) { $('password').value = ''; toast('Connection error: ' + error.message); }
});
$('save').addEventListener('click', save);
$('saveRules').addEventListener('click', save);
$('refresh').addEventListener('click', load);
$('all').addEventListener('click', () => document.querySelectorAll('.enabled').forEach(node => node.checked = true));
$('none').addEventListener('click', () => document.querySelectorAll('.enabled').forEach(node => node.checked = false));
$('sync').addEventListener('click', async () => {
  if (!confirm('Create albums and add indexed media for the saved rules?')) return;
  try {
    const result = await api('sync', {method: 'POST', body: JSON.stringify({confirm: 'SYNC'})});
    toast(`Sync completed: ${result.created} albums created, ${result.added} assets added`);
    await load();
  } catch (error) { toast('Sync error: ' + error.message); }
});
load();
