/* HomeMonitor dashboard — vanilla JS, no external dependencies. */
'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const main = $('#main');

const COLORS = {
  teal: '#2dd4bf',
  blue: '#38bdf8',
  green: '#34d399',
  red: '#fb7185',
  amber: '#fbbf24',
  violet: '#a78bfa',
  muted: '#5d7182',
};

const CATEGORIES = {
  windows: { label: 'WIN', name: 'Windows' },
  linux: { label: 'LNX', name: 'Linux' },
  android: { label: 'AND', name: 'Android' },
  router: { label: 'NET', name: 'Router' },
  other: { label: 'DEV', name: 'Device' },
};

const STATUS_LABELS = {
  online: 'Online',
  offline: 'Offline',
  pending: 'Pending',
  revoked: 'Revoked',
};

const EVENT_META = {
  pairing_requested: { label: 'Pairing requested', icon: 'i-bolt', tone: 'pending' },
  approved: { label: 'Device approved', icon: 'i-check', tone: 'approved' },
  revoked: { label: 'Access revoked', icon: 'i-x', tone: 'offline' },
  online: { label: 'Back online', icon: 'i-wifi', tone: 'online' },
  offline: { label: 'Went offline', icon: 'i-x', tone: 'offline' },
  deleted: { label: 'Device removed', icon: 'i-trash', tone: 'offline' },
};

const RANGES = [
  { minutes: 15, label: '15m' },
  { minutes: 60, label: '1h' },
  { minutes: 360, label: '6h' },
  { minutes: 1440, label: '24h' },
  { minutes: 10080, label: '7d' },
];

// Minimum spacing between SSE-driven refreshes, per page. Keeps an old phone
// responsive when several agents publish heartbeats every few seconds.
const PAGE_REFRESH_MS = {
  overview: 3000,
  devices: 5000,
  device: 5000,
  network: 15000,
  history: 60000,
  alerts: 10000,
  settings: 60000,
};

const state = {
  overview: null,
  route: { name: 'overview', id: null },
  filter: 'all',
  search: '',
  alertFilter: 'active',
  detail: null,
  alerts: null,
  events: [],
  settings: null,
  network: null,
  history: null,
  historyDeviceId: '',
  historyRange: 60,
  live: false,
  stream: null,
  refreshTimer: null,
  lastRefreshAt: 0,
};

class AuthError extends Error {}

/* ------------------------------------------------------------------ helpers */
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function icon(name, className = 'icon') {
  return `<svg class="${className}" aria-hidden="true"><use href="#${name}"/></svg>`;
}

function fmtPct(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return `${Number(value).toFixed(value < 10 ? 1 : 0)}%`;
}

function fmtTemp(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return `${Math.round(Number(value))}°C`;
}

function fmtRate(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const rate = Number(value);
  if (rate < 1024) return `${Math.round(rate)} B/s`;
  if (rate < 1048576) return `${(rate / 1024).toFixed(rate < 10240 ? 1 : 0)} KB/s`;
  return `${(rate / 1048576).toFixed(2)} MB/s`;
}

function fmtMb(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const mb = Number(value);
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

function fmtBytes(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const bytes = Number(value);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1073741824).toFixed(2)} GB`;
}

function fmtFreq(mhz) {
  if (!Number.isFinite(Number(mhz)) || Number(mhz) <= 0) return '—';
  return `${(Number(mhz) / 1000).toFixed(2)} GHz`;
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return '—';
  let value = Math.max(0, Math.floor(Number(seconds)));
  const days = Math.floor(value / 86400);
  value %= 86400;
  const hours = Math.floor(value / 3600);
  value %= 3600;
  const minutes = Math.floor(value / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`;
  if (minutes > 0) return `${minutes}m`;
  return `${value}s`;
}

function timeAgo(timestamp) {
  if (!timestamp) return 'never';
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - Number(timestamp)));
  if (seconds < 8) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function fmtDateTime(timestamp) {
  if (!timestamp) return '—';
  return new Date(Number(timestamp) * 1000).toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function fmtAxisTime(timestamp, spanSeconds) {
  const date = new Date(Number(timestamp) * 1000);
  if (spanSeconds > 172800) {
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }
  const time = date.toLocaleTimeString([], {
    hour: '2-digit', minute: '2-digit', second: spanSeconds <= 3600 && spanSeconds < 1200 ? '2-digit' : undefined,
    hour12: false,
  });
  return time;
}

function usageClass(value) {
  if (value === null || value === undefined) return 'na';
  if (Number(value) >= 90) return 'crit';
  if (Number(value) >= 70) return 'warn';
  return '';
}

function statusBadge(status) {
  return `<span class="status ${esc(status)}">${esc(STATUS_LABELS[status] || status)}</span>`;
}

function categoryOf(device) {
  return CATEGORIES[device.category] || CATEGORIES.other;
}

function deviceIcon(device, extra = '') {
  const category = CATEGORIES[device.category] || CATEGORIES.other;
  return `<div class="device-icon ${esc(device.category || 'other')} ${extra}">${category.label}</div>`;
}

function metricRow(label, value) {
  const available = value !== null && value !== undefined && Number.isFinite(Number(value));
  const width = available ? clamp(Number(value), 0, 100) : 0;
  return `
    <div class="metric">
      <div class="metric-top"><span>${esc(label)}</span><strong class="${available ? '' : 'na'}">${available ? fmtPct(value) : 'N/A'}</strong></div>
      <div class="bar"><i class="${available ? usageClass(value) : 'na'}" style="width:${width}%"></i></div>
    </div>`;
}

function emptyState(title, text, iconName = 'i-devices') {
  return `<div class="empty-state">${icon(iconName)}<strong>${esc(title)}</strong>${esc(text)}</div>`;
}

function statCard({ label, value, foot, accent = '', iconName = 'i-devices', small = false }) {
  return `
    <div class="stat-card ${accent ? `accent-${accent}` : ''}">
      <div class="stat-icon">${icon(iconName)}</div>
      <div class="stat-label">${esc(label)}</div>
      <div class="stat-value ${small ? 'small' : ''}">${value}</div>
      <div class="stat-foot">${foot}</div>
    </div>`;
}

function toast(message, tone = 'info') {
  const stack = $('#toast-stack');
  const element = document.createElement('div');
  element.className = `toast ${tone === 'error' ? 'error' : tone === 'warn' ? 'warn' : ''}`;
  element.textContent = message;
  stack.appendChild(element);
  window.setTimeout(() => {
    element.style.opacity = '0';
    element.style.transform = 'translateY(6px)';
    element.style.transition = 'opacity .2s, transform .2s';
    window.setTimeout(() => element.remove(), 220);
  }, 3800);
}

function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

/* ------------------------------------------------------------------ API */
async function api(path, options = {}) {
  const headers = {
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(path, {
    credentials: 'same-origin',
    cache: 'no-store',
    ...options,
    headers,
  });
  if (response.status === 401) {
    showLogin();
    throw new AuthError('Authentication required');
  }
  let body = {};
  try {
    body = await response.json();
  } catch (error) {
    body = {};
  }
  if (!response.ok) {
    throw new Error(body.error || `Request failed (${response.status})`);
  }
  return body;
}

function post(path, payload = {}) {
  return api(path, { method: 'POST', body: JSON.stringify(payload) });
}

/* ------------------------------------------------------------------ boot & auth */
async function boot() {
  showBoot('Connecting to controller');
  try {
    state.overview = await api('/api/v1/overview');
    hideLogin();
    $('#app').hidden = false;
    $('#boot-screen').hidden = true;
    updateShell();
    startStream();
    await route();
  } catch (error) {
    if (error instanceof AuthError) {
      showLogin();
      return;
    }
    bootError(error.message);
  }
}

function showBoot(message) {
  $('#app').hidden = true;
  $('#login').hidden = true;
  $('#boot-screen').hidden = false;
  const status = $('#boot-status');
  status.innerHTML = '<span class="spinner"></span>';
  status.appendChild(document.createTextNode(' ' + message));
  $('#boot-retry').hidden = true;
}

function bootError(message) {
  $('#app').hidden = true;
  $('#login').hidden = true;
  $('#boot-screen').hidden = false;
  const status = $('#boot-status');
  status.textContent = message || 'Could not reach the controller.';
  $('#boot-retry').hidden = false;
}

function showLogin() {
  stopStream();
  $('#app').hidden = true;
  $('#boot-screen').hidden = true;
  $('#login').hidden = false;
  $('#login-token').value = '';
  $('#login-error').hidden = true;
  window.setTimeout(() => $('#login-token').focus(), 50);
}

function hideLogin() {
  $('#login').hidden = true;
}

function showLoginError(message) {
  const box = $('#login-error');
  box.textContent = message;
  box.hidden = false;
}

/* ------------------------------------------------------------------ router */
function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [name, id] = raw.split('/');
  return { name: name || 'overview', id: id ? decodeURIComponent(id) : null };
}

const PAGE_TITLES = {
  overview: 'Overview',
  devices: 'Devices',
  device: 'Device detail',
  network: 'Network',
  history: 'History',
  alerts: 'Alerts',
  settings: 'Settings',
};

async function route() {
  state.route = parseRoute();
  const name = state.route.name;
  setActiveNav(name);
  $('#topbar-heading').textContent = PAGE_TITLES[name] || 'Overview';
  window.scrollTo({ top: 0, behavior: 'instant' });
  try {
    if (name === 'overview') {
      await loadOverviewPage();
    } else if (name === 'devices') {
      await loadDevicesPage();
    } else if (name === 'device' && state.route.id) {
      await loadDeviceDetail(state.route.id);
    } else if (name === 'network') {
      await loadNetworkPage();
    } else if (name === 'history') {
      await loadHistoryPage();
    } else if (name === 'alerts') {
      await loadAlertsPage();
    } else if (name === 'settings') {
      await loadSettingsPage();
    } else {
      location.replace('#/overview');
    }
    state.lastRefreshAt = Date.now();
  } catch (error) {
    if (error instanceof AuthError) return;
    renderPageError(error);
  }
}

function setActiveNav(name) {
  const target = name === 'device' ? 'devices' : name;
  $$('[data-nav]').forEach((link) => {
    link.classList.toggle('active', link.dataset.nav === target);
  });
}

function renderPageError(error) {
  main.innerHTML = `
    <div class="page">
      <div class="panel">
        <div class="empty-state">
          ${icon('i-alerts')}
          <strong>Could not load this page</strong>
          ${esc(error.message || 'Unknown error')}
          <div style="margin-top:14px"><button class="btn small" data-action="retry">Try again</button></div>
        </div>
      </div>
    </div>`;
}

function loadingPage() {
  main.innerHTML = `
    <div class="page loading-page">
      <div class="loading-block short"></div>
      <div class="loading-block"></div>
      <div class="loading-block"></div>
    </div>`;
}

/* ------------------------------------------------------------------ live stream */
function startStream() {
  stopStream();
  const stream = new EventSource('/api/v1/stream');
  state.stream = stream;
  stream.onopen = () => setLive(true);
  stream.onerror = () => setLive(false);
  stream.onmessage = (event) => {
    if (!event.data) return;
    try {
      const message = JSON.parse(event.data);
      if (message.type === 'ready') {
        setLive(true);
        return;
      }
      setLive(true);
      scheduleRefresh();
    } catch (error) {
      // Ignore malformed events; the next refresh will reconcile state.
    }
  };
}

function stopStream() {
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
  setLive(false);
}

function setLive(live) {
  state.live = live;
  const pill = $('#live-pill');
  pill.classList.toggle('offline', !live);
  $('#live-text').textContent = live ? 'Live' : 'Polling';
}

function scheduleRefresh() {
  if (state.refreshTimer) return;
  const interval = PAGE_REFRESH_MS[state.route.name] || 5000;
  const elapsed = Date.now() - (state.lastRefreshAt || 0);
  const delay = Math.max(350, interval - elapsed);
  state.refreshTimer = window.setTimeout(async () => {
    state.refreshTimer = null;
    await refreshCurrent(true);
  }, delay);
}

async function refreshCurrent(silent = false) {
  const scrollY = window.scrollY;
  const name = state.route.name;
  state.lastRefreshAt = Date.now();
  try {
    if (name === 'overview') {
      state.overview = await api('/api/v1/overview');
      renderOverview();
    } else if (name === 'devices') {
      state.overview = await api('/api/v1/overview');
      updateDeviceGrid();
    } else if (name === 'device' && state.route.id) {
      state.detail = await api(`/api/v1/devices/${encodeURIComponent(state.route.id)}?minutes=15`);
      renderDeviceDetail();
    } else if (name === 'network') {
      state.network = await api('/api/v1/network');
      renderNetworkPage();
    } else if (name === 'alerts') {
      await loadAlertsPage();
    } else if (name === 'settings') {
      if (!silent) await loadSettingsPage();
      return;
    } else if (name === 'history') {
      if (!silent) await loadHistoryPage();
      return;
    } else {
      return;
    }
    updateShell();
    if (scrollY > 0) window.scrollTo({ top: scrollY, behavior: 'instant' });
  } catch (error) {
    if (error instanceof AuthError) return;
    if (!silent) toast(error.message, 'error');
  }
}

/* ------------------------------------------------------------------ shell */
function updateShell() {
  const overview = state.overview;
  if (!overview) return;
  const controller = overview.controller || {};
  const address = (controller.addresses && controller.addresses[0]) || location.hostname;
  $('#controller-host').textContent = `${address}:${controller.port || location.port || 8787}`;
  updateAlertBadge(overview.alert_count || 0);
}

function updateAlertBadge(count) {
  const badge = $('#nav-alert-count');
  badge.textContent = String(count);
  badge.hidden = !count;
}

/* ------------------------------------------------------------------ overview */
async function loadOverviewPage() {
  if (!state.overview) loadingPage();
  state.overview = await api('/api/v1/overview');
  renderOverview();
  updateShell();
}

function pendingBanner(pending) {
  if (!pending || !pending.length) return '';
  const label = pending.length === 1
    ? `<strong>${esc(pending[0].name)} is waiting for approval</strong>`
    : `<strong>${pending.length} devices are waiting for approval</strong>`;
  return `
    <div class="notice-banner">
      <div class="notice-icon">${icon('i-bolt')}</div>
      <div>${label}<span> · Review and approve agents before metrics are accepted.</span></div>
      <a class="btn small" href="#/settings">Review</a>
    </div>`;
}

function renderOverview() {
  const overview = state.overview;
  if (!overview) return;
  const counts = overview.counts;
  const network = overview.network || {};
  const internet = network.internet;
  const netLabel = internet === true ? 'Active' : internet === false ? 'Degraded' : 'Checking';
  const netAccent = internet === true ? 'blue' : internet === false ? 'amber' : 'blue';
  const pending = overview.pending || [];
  const events = overview.events || [];
  const alerts = overview.alerts || [];
  const devices = overview.devices || [];

  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <div class="eyebrow">HomeMonitor · Live overview</div>
          <h1>Network overview</h1>
          <p>Real-time health of every monitored device on your home network.</p>
        </div>
        <div class="page-actions">
          <a class="btn small" href="#/settings">${icon('i-bolt')} Pair a device</a>
        </div>
      </div>

      ${pendingBanner(pending)}

      <div class="stat-grid">
        ${statCard({
          label: 'Total devices',
          value: counts.total,
          foot: 'Registered agents',
          accent: 'teal',
          iconName: 'i-devices',
        })}
        ${statCard({
          label: 'Online',
          value: counts.online,
          foot: 'Active heartbeats',
          accent: 'green',
          iconName: 'i-wifi',
        })}
        ${statCard({
          label: 'Offline',
          value: counts.offline,
          foot: `No heartbeat for ${overview.settings?.offline_after || 15}s`,
          accent: counts.offline ? 'red' : '',
          iconName: 'i-x',
        })}
        ${statCard({
          label: 'Network',
          value: esc(netLabel),
          foot: internet === true ? 'Internet reachable' : internet === false ? 'Internet unreachable' : 'Checking connectivity…',
          accent: netAccent,
          iconName: 'i-network',
          small: true,
        })}
      </div>

      <div class="section-head">
        <div><h2>Devices</h2><p>${devices.length ? `${devices.length} registered · ${counts.online} online` : 'No agents paired yet'}</p></div>
        <a class="panel-link" href="#/devices">View registry ${icon('i-arrow')}</a>
      </div>

      ${devices.length
        ? `<div class="device-grid">${devices.map(deviceCard).join('')}</div>`
        : `<div class="panel">${emptyState('No devices paired yet', 'Open Settings to get the pairing code and connect your first agent.', 'i-devices')}</div>`}

      <div class="overview-lower">
        <div class="panel">
          <div class="panel-head">
            <div><h3>Recent activity</h3><p>Heartbeat transitions and pairing events</p></div>
            <a class="panel-link" href="#/alerts">All alerts</a>
          </div>
          ${timeline(events, 'No activity yet', 'Events will appear as agents connect.')}
        </div>

        <div class="side-stack">
          <div class="panel">
            <div class="panel-head">
              <div><h3>Network</h3><p>Controller connectivity</p></div>
              <a class="panel-link" href="#/network">Details</a>
            </div>
            <div class="net-status">
              <div class="net-status-icon ${internet === false ? 'offline' : internet === null ? 'unknown' : ''}">${icon('i-wifi')}</div>
              <div><h4>${internet === true ? 'Internet active' : internet === false ? 'Internet unreachable' : 'Checking…'}</h4><p>${internet === false ? 'Agents can still report over LAN' : `Last check ${timeAgo(network.checked_at)}`}</p></div>
              <span class="badge ${internet === true ? 'ok' : internet === false ? 'warn' : ''}">${esc(netLabel)}</span>
            </div>
            ${kvRows([
              ['Controller', esc(overview.controller.hostname)],
              ['Address', `<span class="mono">${esc((overview.controller.addresses || []).join(', ') || 'localhost')}</span>`],
              ['Uptime', esc(fmtDuration(overview.controller.uptime_s))],
              ['Devices', `${counts.total} registered`],
            ])}
          </div>

          ${pending.length ? `
            <div class="panel">
              <div class="panel-head"><div><h3>Awaiting approval</h3><p>New agents need your approval</p></div><span class="badge warn">${pending.length}</span></div>
              ${pending.slice(0, 3).map(approvalRow).join('')}
              ${pending.length > 3 ? `<div class="hint-box" style="margin-top:10px">Open <a href="#/settings" style="color:var(--teal)">Settings</a> to review the rest.</div>` : ''}
            </div>` : ''}

          ${alerts.length ? `
            <div class="panel">
              <div class="panel-head"><div><h3>Needs attention</h3><p>Unresolved alerts</p></div><a class="panel-link" href="#/alerts">Open</a></div>
              ${alerts.slice(0, 3).map((alert) => `
                <div class="approval-row">
                  <div class="alert-icon ${esc(alert.severity)}">${icon('i-alerts')}</div>
                  <div class="approval-info"><strong>${esc(alert.title)}</strong><span>${esc(timeAgo(alert.ts))} · ${esc(alert.device_name || 'System')}</span></div>
                </div>`).join('')}
            </div>` : ''}
        </div>
      </div>
    </div>`;
}

function approvalRow(device) {
  return `
    <div class="approval-row">
      ${deviceIcon(device)}
      <div class="approval-info"><strong>${esc(device.name)}</strong><span>${esc(device.os_name)}${device.ip ? ` · ${esc(device.ip)}` : ''}</span></div>
      <div class="approval-actions">
        <button class="btn small primary" data-action="approve" data-id="${esc(device.id)}" data-name="${esc(device.name)}">Approve</button>
      </div>
    </div>`;
}

function deviceCard(device) {
  const latest = device.latest || {};
  const network = device.network || {};
  const temperature = latest.cpu_temp_c ?? latest.gpu_temp_c;
  const searchText = [device.name, device.os_name, device.hostname, device.ip, device.model, network.ssid]
    .filter(Boolean).join(' ').toLowerCase();
  const hasBadges = (temperature !== null && temperature !== undefined)
    || (latest.battery_pct !== null && latest.battery_pct !== undefined)
    || Boolean(network.ssid);
  return `
    <a class="device-card ${device.status === 'pending' ? 'pending' : ''}" href="#/device/${encodeURIComponent(device.id)}"
       data-device-card data-status="${esc(device.status)}" data-search="${esc(searchText)}">
      <div class="device-head">
        ${deviceIcon(device)}
        <div class="device-title">
          <h3>${esc(device.name)}</h3>
          <div class="device-sub"><span>${esc(device.os_name)}</span>${device.os_version ? `<span>· ${esc(device.os_version)}</span>` : ''}</div>
        </div>
        ${statusBadge(device.status)}
      </div>

      ${hasBadges ? `
        <div class="device-badges">
          ${temperature !== null && temperature !== undefined ? `<span class="badge">${icon('i-thermometer')} ${esc(fmtTemp(temperature))}</span>` : ''}
          ${latest.battery_pct !== null && latest.battery_pct !== undefined ? `<span class="badge ${latest.battery_charging ? 'ok' : ''}">${icon('i-battery')} ${esc(fmtPct(latest.battery_pct))}${latest.battery_charging ? ' · charging' : ''}</span>` : ''}
          ${network.ssid ? `<span class="badge">${icon('i-wifi')} ${esc(network.ssid)}${network.signal_pct !== null && network.signal_pct !== undefined ? ` · ${esc(fmtPct(network.signal_pct))}` : ''}</span>` : ''}
        </div>` : ''}

      <div class="metrics">
        ${metricRow('CPU', latest.cpu_pct)}
        ${metricRow('Memory', latest.ram_pct)}
        ${metricRow('GPU', latest.gpu_pct)}
      </div>

      <div class="device-foot">
        <div class="net">
          <span class="down">↓ ${esc(fmtRate(latest.net_down_bps))}</span>
          <span class="up">↑ ${esc(fmtRate(latest.net_up_bps))}</span>
        </div>
        <div class="seen ${device.status === 'offline' ? 'offline' : ''}">
          ${device.status === 'pending' ? 'Awaiting approval' : device.status === 'revoked' ? 'Access revoked' : `${timeAgo(device.last_seen)}`}
        </div>
      </div>
    </a>`;
}

/* ------------------------------------------------------------------ devices */
async function loadDevicesPage() {
  if (!state.overview) loadingPage();
  state.overview = await api('/api/v1/overview');
  renderDevicesPage();
  updateShell();
}

function filterCount(status) {
  const devices = state.overview?.devices || [];
  return status === 'all' ? devices.length : devices.filter((device) => device.status === status).length;
}

function renderDevicesPage() {
  const devices = state.overview?.devices || [];
  const pending = state.overview?.pending || [];
  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <div class="eyebrow">Registry</div>
          <h1>Devices</h1>
          <p>Every paired agent, its latest vitals and connection state.</p>
        </div>
        <div class="page-actions">
          <a class="btn small" href="#/settings">${icon('i-bolt')} Add a device</a>
        </div>
      </div>

      <div id="pending-banner-slot">${pendingBanner(pending)}</div>

      <div class="filter-bar">
        <div class="chips" id="device-filters">
          ${[
            ['all', 'All'],
            ['online', 'Online'],
            ['offline', 'Offline'],
            ['pending', 'Pending'],
          ].map(([value, label]) => `<button class="chip ${state.filter === value ? 'active' : ''}" data-filter="${value}">${label} <span data-count="${value}">${filterCount(value)}</span></button>`).join('')}
        </div>
        <div class="search-box">
          ${icon('i-search')}
          <input id="device-search" type="search" placeholder="Search name, OS, IP…" value="${esc(state.search)}" autocomplete="off">
        </div>
      </div>

      ${devices.length
        ? `<div class="device-grid" id="device-grid">${devices.map(deviceCard).join('')}</div>
           <div id="device-filter-empty" hidden>${emptyState('No matching devices', 'Try a different filter or search term.', 'i-search')}</div>`
        : `<div class="panel">${emptyState('No devices yet', 'Pair your first agent from Settings.', 'i-devices')}</div>`}
    </div>`;
  applyDeviceFilter();
}

function updateDeviceGrid() {
  const grid = $('#device-grid');
  if (!grid || !state.overview || !(state.overview.devices || []).length) {
    renderDevicesPage();
    return;
  }
  grid.innerHTML = (state.overview.devices || []).map(deviceCard).join('');
  const banner = $('#pending-banner-slot');
  if (banner) banner.innerHTML = pendingBanner(state.overview.pending || []);
  for (const [status] of [['all'], ['online'], ['offline'], ['pending']]) {
    const node = main.querySelector(`[data-count="${status}"]`);
    if (node) node.textContent = String(filterCount(status));
  }
  applyDeviceFilter();
}

function applyDeviceFilter() {
  const cards = $$('[data-device-card]', main);
  let visible = 0;
  cards.forEach((card) => {
    const matchesFilter = state.filter === 'all' || card.dataset.status === state.filter;
    const matchesSearch = !state.search || (card.dataset.search || '').includes(state.search);
    const show = matchesFilter && matchesSearch;
    card.classList.toggle('filtered-out', !show);
    if (show) visible += 1;
  });
  const empty = $('#device-filter-empty');
  if (empty) empty.hidden = visible > 0 || !cards.length;
}

/* ------------------------------------------------------------------ device detail */
async function loadDeviceDetail(deviceId) {
  if (!state.detail || state.detail.device?.id !== deviceId) loadingPage();
  state.detail = await api(`/api/v1/devices/${encodeURIComponent(deviceId)}?minutes=15`);
  renderDeviceDetail();
}

function renderDeviceDetail() {
  const detail = state.detail;
  if (!detail) return;
  const device = detail.device;
  const latest = device.latest || {};
  const network = device.network || {};
  const history = detail.history || [];
  const temperature = latest.cpu_temp_c ?? latest.gpu_temp_c;
  const gpuName = latest.gpu_name;

  main.innerHTML = `
    <div class="page">
      <a class="back-link" href="#/devices">${icon('i-back')} All devices</a>

      <div class="detail-hero">
        ${deviceIcon(device)}
        <div class="detail-identity">
          <h1>${esc(device.name)}</h1>
          <p>${esc(device.os_name)}${device.os_version ? ` ${esc(device.os_version)}` : ''}${device.model ? ` · ${esc(device.model)}` : ''}</p>
          <div class="detail-meta">
            ${statusBadge(device.status)}
            <span class="badge">${icon('i-network')} ${esc(network.ip || device.ip || 'No IP')}</span>
            ${network.ssid ? `<span class="badge">${icon('i-wifi')} ${esc(network.ssid)}${network.signal_pct !== null && network.signal_pct !== undefined ? ` · ${esc(fmtPct(network.signal_pct))}` : ''}</span>` : ''}
            <span class="badge">${icon('i-cpu')} ${esc(device.arch || 'unknown')}</span>
            <span class="badge">${icon('i-thermometer')} ${esc(fmtTemp(temperature))}</span>
            ${latest.battery_pct !== null && latest.battery_pct !== undefined ? `<span class="badge">${icon('i-battery')} ${esc(fmtPct(latest.battery_pct))}</span>` : ''}
          </div>
        </div>
        <div class="detail-actions">
          ${device.status === 'pending' ? `<button class="btn primary small" data-action="approve" data-id="${esc(device.id)}" data-name="${esc(device.name)}">Approve</button>` : ''}
          <button class="btn small" data-action="refresh">${icon('i-refresh')} Refresh</button>
          ${device.status !== 'revoked' ? `<button class="btn danger small" data-action="revoke" data-id="${esc(device.id)}" data-name="${esc(device.name)}">Revoke</button>` : ''}
          <button class="btn danger small" data-action="delete" data-id="${esc(device.id)}" data-name="${esc(device.name)}">${icon('i-trash')} Delete</button>
        </div>
      </div>

      <div class="stat-grid detail-stats">
        ${statCard({
          label: 'CPU',
          value: fmtPct(latest.cpu_pct),
          foot: latest.cpu_cores ? `${latest.cpu_cores} threads · ${fmtFreq(latest.cpu_freq_mhz)}` : 'Utilisation',
          accent: 'teal',
          iconName: 'i-cpu',
        })}
        ${statCard({
          label: 'Memory',
          value: fmtPct(latest.ram_pct),
          foot: `${fmtMb(latest.ram_used_mb)} / ${fmtMb(latest.ram_total_mb)}`,
          accent: 'blue',
          iconName: 'i-server',
        })}
        ${statCard({
          label: 'GPU',
          value: latest.gpu_pct !== null && latest.gpu_pct !== undefined ? fmtPct(latest.gpu_pct) : 'N/A',
          foot: gpuName ? esc(gpuName) : 'No supported GPU',
          accent: 'teal',
          iconName: 'i-grid',
        })}
        ${statCard({
          label: 'Temperature',
          value: fmtTemp(temperature),
          foot: latest.cpu_temp_c !== null && latest.cpu_temp_c !== undefined ? 'CPU sensor' : latest.gpu_temp_c !== null && latest.gpu_temp_c !== undefined ? 'GPU sensor' : 'Not exposed',
          accent: 'amber',
          iconName: 'i-thermometer',
        })}
      </div>

      <div class="chart-grid">
        ${chartPanel('cpu', 'CPU utilisation', 'Last 15 minutes', [{ label: 'CPU', color: COLORS.teal }])}
        ${chartPanel('ram', 'Memory usage', 'Last 15 minutes', [{ label: 'RAM', color: COLORS.violet }])}
        ${chartPanel('gpu', 'GPU utilisation', 'NVIDIA telemetry when available', [{ label: 'GPU', color: COLORS.blue }])}
        ${chartPanel('disk', 'Disk usage', 'Primary volume utilisation', [{ label: 'Disk', color: COLORS.violet }])}
        ${chartPanel('network', 'Network throughput', 'Download and upload', [{ label: 'Down', color: COLORS.blue }, { label: 'Up', color: COLORS.green }])}
        ${chartPanel('temp', 'Temperature', 'CPU and GPU sensors', [{ label: 'CPU', color: COLORS.amber }, { label: 'GPU', color: COLORS.red }])}
      </div>

      <div class="detail-lower">
        <div class="panel">
          <div class="panel-head"><div><h3>Top processes</h3><p>Ranked by CPU share</p></div><span class="badge">${(latest.processes || []).length} shown</span></div>
          ${processTable(latest.processes || [])}
        </div>
        <div class="detail-side">
          <div class="panel">
            <div class="panel-head"><div><h3>System</h3><p>Identity and uptime</p></div></div>
            ${kvRows([
              ['Hostname', esc(device.hostname || '—')],
              ['Operating system', esc(device.os_name || '—')],
              ['Version', esc(device.os_version || '—')],
              ['Model', esc(device.model || '—')],
              ['Uptime', esc(fmtDuration(latest.uptime_s))],
              ['Last seen', esc(timeAgo(device.last_seen))],
              ['Agent version', esc(device.agent_version || '—')],
              ['Device ID', `<span class="mono">${esc(device.id)}</span>`],
            ])}
          </div>
          <div class="panel">
            <div class="panel-head"><div><h3>Network</h3><p>Wi-Fi and link details</p></div></div>
            ${kvRows([
              ['Wi-Fi network', esc(network.ssid || '—')],
              ['Signal', network.signal_pct !== null && network.signal_pct !== undefined ? esc(fmtPct(network.signal_pct)) : '—'],
              ['Local IP', `<span class="mono">${esc(network.ip || device.ip || '—')}</span>`],
              ['Gateway', `<span class="mono">${esc(network.gateway || '—')}</span>`],
              ['DNS', `<span class="mono">${esc(network.dns || '—')}</span>`],
              ['Interface', esc(network.interface || '—')],
              ['Link speed', network.link_mbps ? `${esc(network.link_mbps)} Mbps` : '—'],
            ])}
          </div>
          <div class="panel">
            <div class="panel-head"><div><h3>Storage</h3><p>Mounted volumes</p></div></div>
            ${diskList(latest.disks || [])}
          </div>
        </div>
      </div>

      <div class="panel" style="margin-top:13px">
        <div class="panel-head"><div><h3>Connection history</h3><p>Recent events for this device</p></div><a class="panel-link" href="#/alerts">Alerts</a></div>
        ${timeline(detail.events || [], 'No connection events', 'Events appear after the first heartbeat.')}
      </div>
    </div>`;

  requestAnimationFrame(() => drawDetailCharts(history));
}

function chartPanel(id, title, subtitle, legends) {
  return `
    <div class="panel chart-panel">
      <div class="panel-head">
        <div><h3>${esc(title)}</h3><p>${esc(subtitle)}</p></div>
        <div class="legend">${legends.map((item) => `<span class="legend-item"><span class="legend-swatch" style="background:${item.color}"></span>${esc(item.label)}</span>`).join('')}</div>
      </div>
      <div class="chart-wrap">
        <canvas id="chart-${id}" aria-label="${esc(title)} chart"></canvas>
        <div class="chart-empty">Waiting for samples…</div>
      </div>
    </div>`;
}

function processTable(processes) {
  if (!processes.length) return emptyState('No process data', 'The agent has not reported processes yet.', 'i-cpu');
  return `
    <div class="table-wrap">
      <table class="data">
        <thead><tr><th>Process</th><th class="num">PID</th><th class="num">CPU</th><th class="num">RAM</th></tr></thead>
        <tbody>
          ${processes.map((process) => `
            <tr>
              <td><div class="process-cell"><span class="process-dot"></span><span class="process-name" title="${esc(process.name)}">${esc(process.name)}</span></div></td>
              <td class="num mono">${esc(process.pid ?? '—')}</td>
              <td class="num">${esc(fmtPct(process.cpu))}</td>
              <td class="num">${esc(fmtMb(process.mem_mb))}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

function diskList(disks) {
  if (!disks.length) return emptyState('No storage data', 'Disk usage is not available yet.', 'i-disk');
  return disks.map((disk) => `
    <div class="disk-row">
      <div class="disk-top"><span class="mount">${esc(disk.mount)}</span><span class="pct">${esc(fmtPct(disk.percent))}</span></div>
      <div class="bar"><i class="${usageClass(disk.percent)}" style="width:${clamp(Number(disk.percent) || 0, 0, 100)}%"></i></div>
      <div class="disk-sub">${esc(fmtMb(disk.used_gb ? disk.used_gb * 1024 : null))} used of ${esc(fmtMb(disk.total_gb ? disk.total_gb * 1024 : null))}</div>
    </div>`).join('');
}

/* ------------------------------------------------------------------ charts */
function drawChart(canvas, series, options = {}) {
  if (!canvas) return;
  const wrap = canvas.parentElement;
  const empty = wrap?.querySelector('.chart-empty');
  const allPoints = series
    .flatMap((item) => item.points)
    .filter((point) => Array.isArray(point) && Number.isFinite(point[0]) && Number.isFinite(point[1]));
  const rect = canvas.getBoundingClientRect();
  if (empty && options.emptyText) empty.textContent = options.emptyText;
  if (!allPoints.length || rect.width < 20 || rect.height < 20) {
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;

  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const width = rect.width;
  const height = rect.height;
  const pad = { left: 43, right: 8, top: 9, bottom: 22 };
  const plotWidth = Math.max(10, width - pad.left - pad.right);
  const plotHeight = Math.max(10, height - pad.top - pad.bottom);
  const timestamps = allPoints.map((point) => point[0]);
  const values = allPoints.map((point) => point[1]);
  const minX = Math.min(...timestamps);
  const maxX = Math.max(...timestamps);
  let maxY = options.max ?? Math.max(...values);
  if (!options.max) maxY = Math.max(1, maxY) * 1.12;
  const minY = 0;
  const span = Math.max(1, maxY - minY);
  const xFor = (value) => pad.left + (maxX === minX ? plotWidth / 2 : ((value - minX) / (maxX - minX)) * plotWidth);
  const yFor = (value) => pad.top + plotHeight - ((clamp(value, minY, maxY) - minY) / span) * plotHeight;

  ctx.font = '10px ui-monospace, Consolas, monospace';
  ctx.textBaseline = 'middle';
  for (let index = 0; index <= 4; index += 1) {
    const value = maxY - (span * index / 4);
    const y = pad.top + (plotHeight * index / 4);
    ctx.strokeStyle = 'rgba(255,255,255,0.045)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#5d7182';
    ctx.textAlign = 'right';
    const label = options.formatY ? options.formatY(value) : `${Math.round(value)}${options.unit || ''}`;
    ctx.fillText(label, pad.left - 7, y);
  }

  ctx.textAlign = 'left';
  ctx.fillStyle = '#5d7182';
  ctx.fillText(fmtAxisTime(minX, maxX - minX), pad.left, height - 8);
  ctx.textAlign = 'right';
  ctx.fillText(fmtAxisTime(maxX, maxX - minX), width - pad.right, height - 8);
  if (width > 300) {
    ctx.textAlign = 'center';
    ctx.fillText(fmtAxisTime((minX + maxX) / 2, maxX - minX), pad.left + plotWidth / 2, height - 8);
  }

  const fillFirst = options.fill !== false && series.length === 1;
  series.forEach((item, index) => {
    const points = item.points
      .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]))
      .sort((a, b) => a[0] - b[0]);
    if (!points.length) return;
    if (fillFirst && index === 0) {
      const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotHeight);
      gradient.addColorStop(0, hexAlpha(item.color, 0.22));
      gradient.addColorStop(1, hexAlpha(item.color, 0));
      ctx.beginPath();
      points.forEach((point, pointIndex) => {
        const x = xFor(point[0]);
        const y = yFor(point[1]);
        if (pointIndex === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.lineTo(xFor(points[points.length - 1][0]), pad.top + plotHeight);
      ctx.lineTo(xFor(points[0][0]), pad.top + plotHeight);
      ctx.closePath();
      ctx.fillStyle = gradient;
      ctx.fill();
    }
    ctx.strokeStyle = item.color;
    ctx.lineWidth = 1.9;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();
    points.forEach((point, pointIndex) => {
      const x = xFor(point[0]);
      const y = yFor(point[1]);
      if (pointIndex === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    const last = points[points.length - 1];
    ctx.fillStyle = item.color;
    ctx.beginPath();
    ctx.arc(xFor(last[0]), yFor(last[1]), 2.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = 'rgba(7,11,15,0.9)';
    ctx.beginPath();
    ctx.arc(xFor(last[0]), yFor(last[1]), 1.1, 0, Math.PI * 2);
    ctx.fill();
  });
}

function hexAlpha(hex, alpha) {
  const value = hex.replace('#', '');
  const bigint = parseInt(value.length === 3 ? value.split('').map((c) => c + c).join('') : value, 16);
  const r = (bigint >> 16) & 255;
  const g = (bigint >> 8) & 255;
  const b = bigint & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function pointsFor(history, key) {
  return history
    .filter((point) => point[key] !== null && point[key] !== undefined && Number.isFinite(Number(point[key])))
    .map((point) => [Number(point.ts), Number(point[key])]);
}

function drawDetailCharts(history) {
  const points = history || [];
  drawChart($('#chart-cpu'), [{
    color: COLORS.teal,
    points: pointsFor(points, 'cpu_pct'),
  }], { max: 100, formatY: (value) => `${Math.round(value)}%` });

  drawChart($('#chart-ram'), [{
    color: COLORS.violet,
    points: pointsFor(points, 'ram_pct'),
  }], { max: 100, formatY: (value) => `${Math.round(value)}%` });

  drawChart($('#chart-gpu'), [{
    color: COLORS.blue,
    points: pointsFor(points, 'gpu_pct'),
  }], { max: 100, formatY: (value) => `${Math.round(value)}%`, emptyText: 'No supported GPU telemetry' });

  drawChart($('#chart-disk'), [{
    color: COLORS.violet,
    points: pointsFor(points, 'disk_pct'),
  }], { max: 100, formatY: (value) => `${Math.round(value)}%`, emptyText: 'No disk telemetry' });

  drawChart($('#chart-network'), [
    { color: COLORS.blue, points: pointsFor(points, 'net_down_bps') },
    { color: COLORS.green, points: pointsFor(points, 'net_up_bps') },
  ], { formatY: (value) => fmtRate(value), fill: false });

  const cpuTemps = pointsFor(points, 'cpu_temp_c');
  const gpuTemps = pointsFor(points, 'gpu_temp_c');
  drawChart($('#chart-temp'), [
    { color: COLORS.amber, points: cpuTemps },
    { color: COLORS.red, points: gpuTemps },
  ], { formatY: (value) => `${Math.round(value)}°`, fill: false, emptyText: 'No temperature sensor' });
}

/* ------------------------------------------------------------------ history */
async function loadHistoryPage() {
  if (!state.overview) loadingPage();
  state.overview = await api('/api/v1/overview');
  const devices = state.overview.devices || [];
  if (!devices.length) {
    main.innerHTML = `<div class="page"><div class="page-head"><div><div class="eyebrow">History</div><h1>Performance history</h1></div></div><div class="panel">${emptyState('No history yet', 'Pair a device and collect some samples first.', 'i-history')}</div></div>`;
    return;
  }
  if (!state.historyDeviceId || !devices.some((device) => device.id === state.historyDeviceId)) {
    const online = devices.find((device) => device.status === 'online');
    state.historyDeviceId = (online || devices[0]).id;
  }
  state.history = await api(`/api/v1/devices/${encodeURIComponent(state.historyDeviceId)}/history?minutes=${state.historyRange}`);
  renderHistoryPage();
  updateShell();
}

function renderHistoryPage() {
  const devices = state.overview?.devices || [];
  const history = state.history?.points || [];
  const device = devices.find((item) => item.id === state.historyDeviceId);
  const summary = summarize(history);
  const range = RANGES.find((item) => item.minutes === state.historyRange) || RANGES[1];

  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <div class="eyebrow">History</div>
          <h1>Performance history</h1>
          <p>Stored samples from the controller database. Raw history is pruned by the retention policy.</p>
        </div>
        <div class="page-actions">
          <div class="toolbar">
            <select id="history-device" aria-label="Select device">
              ${devices.map((item) => `<option value="${esc(item.id)}" ${item.id === state.historyDeviceId ? 'selected' : ''}>${esc(item.name)} · ${esc(item.os_name)}</option>`).join('')}
            </select>
          </div>
        </div>
      </div>

      <div class="toolbar" style="margin-bottom:16px">
        <div class="chips">
          ${RANGES.map((item) => `<button class="chip ${item.minutes === state.historyRange ? 'active' : ''}" data-range="${item.minutes}">${item.label}</button>`).join('')}
        </div>
        <span class="badge">${history.length} samples · ${esc(device?.name || '')}</span>
      </div>

      <div class="summary-grid">
        <div class="summary-card"><span>Average CPU</span><strong>${esc(fmtPct(summary.cpuAvg))}</strong></div>
        <div class="summary-card"><span>Peak CPU</span><strong>${esc(fmtPct(summary.cpuMax))}</strong></div>
        <div class="summary-card"><span>Average memory</span><strong>${esc(fmtPct(summary.ramAvg))}</strong></div>
        <div class="summary-card"><span>Peak temperature</span><strong>${esc(fmtTemp(summary.tempMax))}</strong></div>
      </div>

      <div class="chart-grid">
        ${chartPanel('history-cpu', 'CPU utilisation', `Last ${range.label}`, [{ label: 'CPU', color: COLORS.teal }])}
        ${chartPanel('history-ram', 'Memory usage', `Last ${range.label}`, [{ label: 'RAM', color: COLORS.violet }])}
        ${chartPanel('history-gpu', 'GPU utilisation', `Last ${range.label}`, [{ label: 'GPU', color: COLORS.blue }])}
        ${chartPanel('history-disk', 'Disk usage', `Last ${range.label}`, [{ label: 'Disk', color: COLORS.violet }])}
        ${chartPanel('history-network', 'Network throughput', `Last ${range.label}`, [{ label: 'Down', color: COLORS.blue }, { label: 'Up', color: COLORS.green }])}
        ${chartPanel('history-temp', 'Temperature', `Last ${range.label}`, [{ label: 'CPU', color: COLORS.amber }, { label: 'GPU', color: COLORS.red }])}
      </div>

      <div class="panel" style="margin-top:13px">
        <div class="panel-head"><div><h3>Storage & power</h3><p>Latest values for ${esc(device?.name || 'device')}</p></div></div>
        <div class="form-grid">
          <div>${diskList(device?.latest?.disks || [])}</div>
          <div>${kvRows([
            ['Battery', device?.latest?.battery_pct !== null && device?.latest?.battery_pct !== undefined ? esc(fmtPct(device.latest.battery_pct)) : '—'],
            ['Charging', device?.latest?.battery_charging ? 'Yes' : 'No'],
            ['Disk usage', esc(fmtPct(device?.latest?.disk_pct))],
            ['Uptime', esc(fmtDuration(device?.latest?.uptime_s))],
            ['Last sample', esc(fmtDateTime(history[history.length - 1]?.ts))],
          ])}</div>
        </div>
      </div>
    </div>`;

  requestAnimationFrame(() => drawHistoryCharts());
}

function summarize(points) {
  const values = (key) => points.map((point) => point[key]).filter((value) => Number.isFinite(Number(value))).map(Number);
  const average = (items) => (items.length ? items.reduce((a, b) => a + b, 0) / items.length : null);
  const cpu = values('cpu_pct');
  const ram = values('ram_pct');
  const temps = [...values('cpu_temp_c'), ...values('gpu_temp_c')];
  return {
    cpuAvg: average(cpu),
    cpuMax: cpu.length ? Math.max(...cpu) : null,
    ramAvg: average(ram),
    tempMax: temps.length ? Math.max(...temps) : null,
  };
}

function drawHistoryCharts() {
  const points = state.history?.points || [];
  drawChart($('#chart-history-cpu'), [{ color: COLORS.teal, points: pointsFor(points, 'cpu_pct') }], { max: 100, formatY: (value) => `${Math.round(value)}%` });
  drawChart($('#chart-history-ram'), [{ color: COLORS.violet, points: pointsFor(points, 'ram_pct') }], { max: 100, formatY: (value) => `${Math.round(value)}%` });
  drawChart($('#chart-history-gpu'), [{ color: COLORS.blue, points: pointsFor(points, 'gpu_pct') }], { max: 100, formatY: (value) => `${Math.round(value)}%`, emptyText: 'No supported GPU telemetry' });
  drawChart($('#chart-history-disk'), [{ color: COLORS.violet, points: pointsFor(points, 'disk_pct') }], { max: 100, formatY: (value) => `${Math.round(value)}%`, emptyText: 'No disk telemetry' });
  drawChart($('#chart-history-network'), [
    { color: COLORS.blue, points: pointsFor(points, 'net_down_bps') },
    { color: COLORS.green, points: pointsFor(points, 'net_up_bps') },
  ], { formatY: (value) => fmtRate(value), fill: false });
  drawChart($('#chart-history-temp'), [
    { color: COLORS.amber, points: pointsFor(points, 'cpu_temp_c') },
    { color: COLORS.red, points: pointsFor(points, 'gpu_temp_c') },
  ], { formatY: (value) => `${Math.round(value)}°`, fill: false, emptyText: 'No temperature sensor' });
}

/* ------------------------------------------------------------------ network */
async function loadNetworkPage() {
  if (!state.network) loadingPage();
  state.network = await api('/api/v1/network');
  renderNetworkPage();
}

function renderNetworkPage() {
  const network = state.network;
  if (!network) return;
  const controller = network.controller;
  const wifi = controller.network || {};
  const internet = network.internet || {};
  const devices = network.devices || [];
  const online = devices.filter((device) => device.status === 'online').length;
  const addresses = (controller.addresses || []).join(', ') || 'localhost';

  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <div class="eyebrow">Network</div>
          <h1>LAN & connectivity</h1>
          <p>Controller reachability, internet access and the IP addresses reported by agents.</p>
        </div>
      </div>

      <div class="stat-grid">
        ${statCard({
          label: 'Internet',
          value: internet.internet === true ? 'Active' : internet.internet === false ? 'Down' : 'Checking',
          foot: internet.checked_at ? `Checked ${timeAgo(internet.checked_at)}` : 'Waiting for first check',
          accent: internet.internet === false ? 'amber' : 'blue',
          iconName: 'i-wifi',
          small: true,
        })}
        ${statCard({ label: 'Agents online', value: `${online}/${devices.length}`, foot: 'Heartbeat status', accent: 'green', iconName: 'i-devices' })}
        ${statCard({ label: 'Controller', value: esc(controller.hostname || '—'), foot: esc(controller.platform || ''), accent: 'teal', iconName: 'i-server', small: true })}
        ${statCard({ label: 'Uptime', value: esc(fmtDuration(controller.uptime_s)), foot: `v${esc(controller.version || '—')} · port ${esc(controller.port)}`, accent: 'blue', iconName: 'i-history', small: true })}
      </div>

      <div class="settings-grid">
        <div class="panel">
          <div class="panel-head"><div><h3>Connectivity</h3><p>Controller's view of the network</p></div></div>
          <div class="net-status">
            <div class="net-status-icon ${internet.internet === false ? 'offline' : internet.internet === null ? 'unknown' : ''}">${icon('i-wifi')}</div>
            <div><h4>${internet.internet === true ? 'Internet reachable' : internet.internet === false ? 'No internet route' : 'Checking internet…'}</h4><p>TCP probe to public DNS resolvers</p></div>
            <span class="badge ${internet.internet === true ? 'ok' : 'warn'}">${internet.internet === true ? 'Active' : internet.internet === false ? 'Degraded' : 'Unknown'}</span>
          </div>
          ${kvRows([
            ['LAN address', `<span class="mono">${esc(addresses)}</span>`],
            ['Wi-Fi network', esc(wifi.ssid || '—')],
            ['Signal', wifi.signal_pct !== null && wifi.signal_pct !== undefined ? esc(fmtPct(wifi.signal_pct)) : '—'],
            ['Gateway', `<span class="mono">${esc(wifi.gateway || '—')}</span>`],
            ['DNS', `<span class="mono">${esc(wifi.dns || '—')}</span>`],
            ['HTTP port', esc(controller.port)],
            ['Controller OS', esc(controller.platform)],
            ['Data directory', `<span class="mono">${esc(controller.data_dir)}</span>`],
            ['Database size', esc(fmtBytes(controller.db_bytes))],
            ['Last check', esc(fmtDateTime(internet.checked_at))],
          ])}
        </div>

        <div class="panel">
          <div class="panel-head"><div><h3>Router integration</h3><p>Phase 8</p></div><span class="badge warn">Not configured</span></div>
          ${emptyState('Router telemetry is not enabled', 'Connected-client lists, WAN stats and LAN latency will be added in the network discovery phase. Agent heartbeats already give you reachability per device.', 'i-network')}
        </div>
      </div>

      <div class="panel" style="margin-top:13px">
        <div class="panel-head"><div><h3>Device addresses</h3><p>Reported by agent heartbeats</p></div><span class="badge">${devices.length} devices</span></div>
        ${networkDeviceTable(devices)}
      </div>
    </div>`;
}

function networkDeviceTable(devices) {
  if (!devices.length) return emptyState('No agents connected', 'Pair an agent to populate the address table.', 'i-devices');
  return `
    <div class="table-wrap">
      <table class="data">
        <thead><tr><th>Device</th><th>Category</th><th>IP address</th><th>Wi-Fi</th><th>Signal</th><th>Status</th><th class="num">Last seen</th></tr></thead>
        <tbody>
          ${devices.map((device) => {
            const net = device.network || {};
            return `
            <tr>
              <td><a href="#/device/${encodeURIComponent(device.id)}" style="color:#e8f0f7">${esc(device.name)}</a></td>
              <td>${esc((CATEGORIES[device.category] || CATEGORIES.other).name)}</td>
              <td class="mono">${esc(net.ip || device.ip || '—')}</td>
              <td>${esc(net.ssid || '—')}</td>
              <td>${net.signal_pct !== null && net.signal_pct !== undefined ? esc(fmtPct(net.signal_pct)) : '—'}</td>
              <td>${statusBadge(device.status)}</td>
              <td class="num">${esc(timeAgo(device.last_seen))}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>`;
}

/* ------------------------------------------------------------------ alerts */
async function loadAlertsPage() {
  const [alertsResponse, eventsResponse] = await Promise.all([
    api('/api/v1/alerts?limit=200'),
    api('/api/v1/events?limit=25'),
  ]);
  state.alerts = alertsResponse.alerts || [];
  state.events = eventsResponse.events || [];
  const unresolved = state.alerts.filter((alert) => !alert.resolved_at).length;
  updateAlertBadge(unresolved);
  renderAlertsPage();
}

function renderAlertsPage() {
  const alerts = state.alerts || [];
  const active = alerts.filter((alert) => !alert.resolved_at);
  const filtered = alerts.filter((alert) => {
    if (state.alertFilter === 'active') return !alert.resolved_at;
    if (state.alertFilter === 'resolved') return Boolean(alert.resolved_at);
    return true;
  });

  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <div class="eyebrow">Alerts</div>
          <h1>Alerts & events</h1>
          <p>Disconnection warnings, approval events and recovery notices.</p>
        </div>
        <div class="page-actions">
          <span class="badge ${active.length ? 'warn' : 'ok'}">${active.length} active</span>
        </div>
      </div>

      <div class="toolbar" style="margin-bottom:14px">
        <div class="chips">
          ${[
            ['active', `Active (${active.length})`],
            ['resolved', 'Resolved'],
            ['all', `All (${alerts.length})`],
          ].map(([value, label]) => `<button class="chip ${state.alertFilter === value ? 'active' : ''}" data-alert-filter="${value}">${label}</button>`).join('')}
        </div>
      </div>

      <div class="panel">
        <div class="alert-list">
          ${filtered.length ? filtered.map(alertRow).join('') : emptyState(state.alertFilter === 'active' ? 'No active alerts' : 'No alerts in this view', 'Everything looks quiet right now.', 'i-check')}
        </div>
      </div>

      <div class="panel" style="margin-top:13px">
        <div class="panel-head"><div><h3>Recent events</h3><p>Raw activity log</p></div></div>
        ${timeline(state.events || [], 'No events yet', 'Agents will generate events as they connect.')}
      </div>
    </div>`;
}

function alertRow(alert) {
  const resolved = Boolean(alert.resolved_at);
  return `
    <div class="alert-item ${resolved ? 'resolved' : ''}">
      <div class="alert-icon ${esc(alert.severity || 'info')}">${icon(alert.kind === 'offline' ? 'i-wifi' : 'i-alerts')}</div>
      <div class="alert-body">
        <h4>${esc(alert.title)}</h4>
        <p>${esc(alert.detail || '')}</p>
        <div class="alert-meta">
          <span>${esc(alert.device_name || 'System')}</span>
          <span>·</span>
          <span>${esc(fmtDateTime(alert.ts))} (${esc(timeAgo(alert.ts))})</span>
          ${alert.acknowledged ? '<span class="badge">Acknowledged</span>' : ''}
          ${resolved ? '<span class="badge ok">Resolved</span>' : ''}
        </div>
      </div>
      <div class="alert-actions">
        ${!alert.acknowledged && !resolved ? `<button class="btn small ghost" data-action="ack" data-id="${esc(alert.id)}">Acknowledge</button>` : ''}
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ settings */
async function loadSettingsPage() {
  if (!state.settings) loadingPage();
  const [settingsResponse, overview] = await Promise.all([
    api('/api/v1/settings'),
    api('/api/v1/overview'),
  ]);
  state.settings = settingsResponse;
  state.overview = overview;
  renderSettingsPage();
  updateShell();
}

function renderSettingsPage() {
  if (!state.settings) return;
  const settings = state.settings.settings;
  const controller = state.settings.controller;
  const pairingCode = state.settings.pairing_code;
  const pending = state.overview?.pending || [];
  const devices = state.overview?.devices || [];
  const address = (controller.addresses && controller.addresses[0]) || location.hostname;
  const command = `python -m agent --controller http://${address}:${controller.port} --pairing-code ${pairingCode}`;

  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <div class="eyebrow">Settings</div>
          <h1>Controller settings</h1>
          <p>Pairing, monitoring intervals, retention and device access.</p>
        </div>
      </div>

      <div class="settings-grid">
        <div class="panel">
          <div class="panel-head"><div><h3>Pairing</h3><p>Enter this code once when installing an agent</p></div></div>
          <div class="pairing-code">
            <span>${esc(pairingCode)}</span>
            <button class="btn small" data-copy="${esc(pairingCode)}" title="Copy pairing code">${icon('i-copy')} Copy</button>
          </div>
          <div style="margin-top:11px">
            <div class="hint-box">${icon('i-bolt')}<div>On the new device, run the agent with this controller address and code. Approve it below after it appears.<br><code>${esc(command)}</code></div></div>
          </div>
          <div class="settings-actions">
            <button class="btn small" data-copy="${esc(command)}">${icon('i-copy')} Copy command</button>
            <button class="btn danger small" data-action="regenerate">Regenerate code</button>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head"><div><h3>Monitoring & retention</h3><p>Applies to agents on their next heartbeat</p></div></div>
          <form data-form="settings">
            <div class="form-grid">
              <label class="field"><span>Heartbeat interval (s)</span><input name="heartbeat_interval" type="number" min="2" max="60" value="${esc(settings.heartbeat_interval)}" required><small>Every agent sends a heartbeat at this cadence.</small></label>
              <label class="field"><span>Metrics interval (s)</span><input name="metrics_interval" type="number" min="2" max="60" value="${esc(settings.metrics_interval)}" required><small>Detailed vitals upload frequency.</small></label>
              <label class="field"><span>Offline threshold (s)</span><input name="offline_after" type="number" min="10" max="300" value="${esc(settings.offline_after)}" required><small>No heartbeat for this long marks a device offline.</small></label>
              <label class="field"><span>Metric retention (days)</span><input name="retention_days" type="number" min="1" max="90" value="${esc(settings.retention_days)}" required><small>Raw samples older than this are deleted.</small></label>
              <label class="field"><span>Event retention (days)</span><input name="events_retention_days" type="number" min="1" max="180" value="${esc(settings.events_retention_days)}" required><small>Connection events and resolved alerts.</small></label>
            </div>
            <div class="settings-actions"><button class="btn primary small" type="submit">Save settings</button></div>
          </form>
        </div>

        <div class="panel span-2">
          <div class="panel-head"><div><h3>Device access</h3><p>Approve new agents or revoke an existing token</p></div><span class="badge">${devices.length} registered</span></div>
          ${pending.length ? `<div class="notice-banner" style="margin-bottom:13px"><div class="notice-icon">${icon('i-bolt')}</div><div><strong>${pending.length} awaiting approval</strong><span> · Metrics are rejected until you approve.</span></div></div>` : ''}
          ${devices.length ? `<div class="device-access-list">${devices.map(deviceAccessRow).join('')}</div>` : emptyState('No devices paired', 'Use the pairing code above to connect an agent.', 'i-devices')}
        </div>

        <div class="panel span-2">
          <div class="panel-head"><div><h3>Controller & security</h3><p>HomeMonitor v${esc(controller.version)}</p></div></div>
          <div class="settings-grid">
            <div>${kvRows([
              ['Hostname', esc(controller.hostname)],
              ['Platform', esc(controller.platform)],
              ['LAN address', `<span class="mono">${esc((controller.addresses || []).join(', ') || 'localhost')}</span>`],
              ['HTTP port', esc(controller.port)],
              ['Uptime', esc(fmtDuration(controller.uptime_s))],
            ])}</div>
            <div>${kvRows([
              ['Data directory', `<span class="mono">${esc(controller.data_dir)}</span>`],
              ['Database size', esc(fmtBytes(controller.db_bytes))],
              ['Schema', esc(controller.schema)],
              ['Auth', 'Per-device tokens'],
              ['Transport', 'LAN HTTP'],
            ])}</div>
          </div>
          <div class="hint-box" style="margin-top:12px">${icon('i-settings')}<div>This controller is designed for a trusted LAN. Do not expose the port to the internet without a TLS reverse proxy and firewall rules. Device tokens are stored as SHA-256 hashes; the dashboard session is an HttpOnly cookie.</div></div>
          <div class="settings-actions"><button class="btn ghost small" id="settings-logout">${icon('i-logout')} Sign out</button></div>
        </div>
      </div>
    </div>`;
}

function deviceAccessRow(device) {
  return `
    <div class="device-access-row">
      ${deviceIcon(device)}
      <div class="device-access-info">
        <strong>${esc(device.name)}</strong>
        <span>${esc(device.os_name)} · ${esc(device.ip || 'no IP')} · ${esc(STATUS_LABELS[device.status] || device.status)}</span>
      </div>
      ${statusBadge(device.status)}
      <div class="device-access-actions">
        ${device.status === 'pending' ? `<button class="btn primary small" data-action="approve" data-id="${esc(device.id)}" data-name="${esc(device.name)}">Approve</button>` : ''}
        ${device.status !== 'revoked' ? `<button class="btn small ghost" data-action="revoke" data-id="${esc(device.id)}" data-name="${esc(device.name)}">Revoke</button>` : ''}
        <a class="btn small ghost" href="#/device/${encodeURIComponent(device.id)}">View</a>
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ timeline & kv */
function kvRows(rows) {
  return `<div class="kv">${rows.map(([key, value]) => `<div class="kv-row"><span class="k">${esc(key)}</span><span class="v">${value}</span></div>`).join('')}</div>`;
}

function timeline(events, emptyTitle, emptyText) {
  if (!events || !events.length) return emptyState(emptyTitle, emptyText, 'i-history');
  return `<div class="timeline">${events.map((event) => {
    const meta = EVENT_META[event.kind] || { label: event.kind, icon: 'i-history', tone: '' };
    return `
      <div class="timeline-item">
        <div class="timeline-dot ${meta.tone}">${icon(meta.icon)}</div>
        <div class="timeline-body">
          <strong>${esc(event.device_name ? `${event.device_name} · ${meta.label}` : meta.label)}</strong>
          <span>${esc(event.detail || '')}</span>
        </div>
        <div class="timeline-time">${esc(timeAgo(event.ts))}</div>
      </div>`;
  }).join('')}</div>`;
}

/* ------------------------------------------------------------------ actions */
async function runAction(button, task) {
  if (button) button.disabled = true;
  try {
    await task();
  } catch (error) {
    if (!(error instanceof AuthError)) toast(error.message, 'error');
  } finally {
    if (button && button.isConnected) button.disabled = false;
  }
}

async function approveDevice(deviceId, button) {
  await runAction(button, async () => {
    await post(`/api/v1/devices/${encodeURIComponent(deviceId)}/approve`);
    toast('Device approved');
    if (state.route.name === 'settings') await loadSettingsPage();
    else if (state.route.name === 'device') await loadDeviceDetail(state.route.id);
    else if (state.route.name === 'devices') await loadDevicesPage();
    else await loadOverviewPage();
  });
}

async function revokeDevice(deviceId, button) {
  if (!window.confirm('Revoke this device? Its token stops working and it must be paired again.')) return;
  await runAction(button, async () => {
    await post(`/api/v1/devices/${encodeURIComponent(deviceId)}/revoke`);
    toast('Device access revoked', 'warn');
    if (state.route.name === 'settings') await loadSettingsPage();
    else if (state.route.name === 'device') await loadDeviceDetail(state.route.id);
    else if (state.route.name === 'devices') await loadDevicesPage();
    else await loadOverviewPage();
  });
}

async function deleteDevice(deviceId, button) {
  if (!window.confirm('Delete this device and all of its stored history? This cannot be undone.')) return;
  await runAction(button, async () => {
    await api(`/api/v1/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' });
    toast('Device deleted');
    if (state.route.name === 'device') {
      location.hash = '#/devices';
    } else if (state.route.name === 'settings') {
      await loadSettingsPage();
    } else if (state.route.name === 'devices') {
      await loadDevicesPage();
    } else {
      await loadOverviewPage();
    }
  });
}

async function acknowledgeAlert(alertId, button) {
  await runAction(button, async () => {
    await post(`/api/v1/alerts/${encodeURIComponent(alertId)}/ack`);
    toast('Alert acknowledged');
    await loadAlertsPage();
  });
}

async function regeneratePairing(button) {
  if (!window.confirm('Regenerate the pairing code? Existing agents keep working; new agents need the new code.')) return;
  await runAction(button, async () => {
    const result = await post('/api/v1/pairing/regenerate');
    if (state.settings) state.settings.pairing_code = result.pairing_code;
    toast('New pairing code generated');
    await loadSettingsPage();
  });
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    }
    toast('Copied to clipboard');
  } catch (error) {
    toast('Could not copy; select the text manually', 'error');
  }
}

/* ------------------------------------------------------------------ events */
function bindEvents() {
  window.addEventListener('hashchange', () => {
    if (state.overview) route();
  });

  $('#refresh-button').addEventListener('click', async () => {
    const button = $('#refresh-button');
    button.classList.add('loading');
    await refreshCurrent(false);
    button.classList.remove('loading');
  });

  $('#logout-button').addEventListener('click', logout);
  document.addEventListener('click', (event) => {
    if (event.target.closest('#settings-logout')) logout();
  });

  $('#login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('#login-button');
    const token = $('#login-token').value.trim();
    if (!token) return;
    button.disabled = true;
    button.textContent = 'Connecting…';
    $('#login-error').hidden = true;
    try {
      await api('/api/v1/session', { method: 'POST', body: JSON.stringify({ token }) });
      hideLogin();
      await boot();
    } catch (error) {
      if (!(error instanceof AuthError)) showLoginError(error.message);
      else showLoginError('Invalid admin token. Check the controller console.');
    } finally {
      button.disabled = false;
      button.textContent = 'Connect to controller';
    }
  });

  $('#boot-retry').addEventListener('click', boot);

  main.addEventListener('click', (event) => {
    const filter = event.target.closest('[data-filter]');
    if (filter) {
      state.filter = filter.dataset.filter;
      $$('[data-filter]', main).forEach((button) => button.classList.toggle('active', button === filter));
      applyDeviceFilter();
      return;
    }

    const alertFilter = event.target.closest('[data-alert-filter]');
    if (alertFilter) {
      state.alertFilter = alertFilter.dataset.alertFilter;
      renderAlertsPage();
      return;
    }

    const range = event.target.closest('[data-range]');
    if (range) {
      state.historyRange = Number(range.dataset.range);
      loadHistoryPage().catch((error) => {
        if (!(error instanceof AuthError)) toast(error.message, 'error');
      });
      return;
    }

    const copy = event.target.closest('[data-copy]');
    if (copy) {
      copyText(copy.dataset.copy);
      return;
    }

    const actionElement = event.target.closest('[data-action]');
    if (!actionElement) return;
    const { action, id } = actionElement.dataset;
    if (action === 'approve' && id) approveDevice(id, actionElement);
    else if (action === 'revoke' && id) revokeDevice(id, actionElement);
    else if (action === 'delete' && id) deleteDevice(id, actionElement);
    else if (action === 'ack' && id) acknowledgeAlert(id, actionElement);
    else if (action === 'regenerate') regeneratePairing(actionElement);
    else if (action === 'refresh' || action === 'retry') refreshCurrent(false);
  });

  main.addEventListener('input', (event) => {
    if (event.target.id === 'device-search') {
      state.search = event.target.value.trim().toLowerCase();
      applyDeviceFilter();
    }
  });

  main.addEventListener('change', (event) => {
    if (event.target.id === 'history-device') {
      state.historyDeviceId = event.target.value;
      loadHistoryPage().catch((error) => {
        if (!(error instanceof AuthError)) toast(error.message, 'error');
      });
    }
  });

  main.addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-form="settings"]');
    if (!form) return;
    event.preventDefault();
    const payload = {};
    for (const [key, value] of new FormData(form).entries()) {
      payload[key] = Number(value);
    }
    const button = form.querySelector('button[type="submit"]');
    await runAction(button, async () => {
      const response = await api('/api/v1/settings', {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      state.settings = response;
      toast('Settings saved');
      await loadSettingsPage();
    });
  });

  const redraw = debounce(() => {
    if (state.route.name === 'device' && state.detail) drawDetailCharts(state.detail.history);
    if (state.route.name === 'history' && state.history) drawHistoryCharts();
  }, 120);
  window.addEventListener('resize', redraw);

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && state.overview) scheduleRefresh();
  });

  window.setInterval(() => {
    const now = new Date();
    $('#clock').textContent = now.toLocaleTimeString([], { hour12: false });
  }, 1000);
  $('#clock').textContent = new Date().toLocaleTimeString([], { hour12: false });

  window.setInterval(() => {
    if (!state.live && state.overview && !document.hidden) refreshCurrent(true);
  }, 20000);
}

async function logout() {
  try {
    await api('/api/v1/session', { method: 'DELETE' });
  } catch (error) {
    // Ignore: clear local state regardless.
  }
  stopStream();
  state.overview = null;
  state.detail = null;
  state.settings = null;
  state.network = null;
  state.history = null;
  state.alerts = null;
  showLogin();
}

function init() {
  bindEvents();
  boot();
}

document.addEventListener('DOMContentLoaded', init);
