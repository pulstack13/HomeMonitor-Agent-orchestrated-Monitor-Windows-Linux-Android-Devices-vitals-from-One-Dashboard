(function () {
  'use strict';

  var REFRESH_MS = 5000;
  var loading = false;
  var refreshTimer = null;
  var clockTimer = null;

  function $(id) { return document.getElementById(id); }

  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function num(value) {
    return typeof value === 'number' && isFinite(value) ? value : null;
  }

  function pct(value) {
    var n = num(value);
    return n === null ? '—' : n.toFixed(1) + '%';
  }

  function temp(value) {
    var n = num(value);
    return n === null ? null : n.toFixed(0) + '°C';
  }

  function rate(value) {
    var n = num(value);
    if (n === null) return '—';
    if (n < 1024) return n.toFixed(0) + ' B/s';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB/s';
    return (n / 1048576).toFixed(1) + ' MB/s';
  }

  function bytes(value) {
    var n = num(value);
    if (n === null) return '—';
    if (n < 1024) return n.toFixed(0) + ' B';
    if (n < 1048576) return (n / 1024).toFixed(0) + ' KB';
    if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
    return (n / 1073741824).toFixed(2) + ' GB';
  }

  function uptime(value) {
    var n = num(value);
    if (n === null) return '—';
    n = Math.max(0, Math.floor(n));
    var days = Math.floor(n / 86400);
    var hours = Math.floor((n % 86400) / 3600);
    var minutes = Math.floor((n % 3600) / 60);
    if (days) return days + 'd ' + hours + 'h';
    if (hours) return hours + 'h ' + minutes + 'm';
    return minutes + 'm';
  }

  function bar(label, value) {
    var n = num(value);
    var width = n === null ? 0 : Math.max(0, Math.min(100, n));
    var tone = n !== null && n >= 90 ? ' crit' : n !== null && n >= 80 ? ' warn' : '';
    return '<div class="bar' + tone + '"><span class="k">' + esc(label) + '</span>' +
      '<div class="track"><i style="width:' + width.toFixed(1) + '%"></i></div>' +
      '<b>' + esc(pct(value)) + '</b></div>';
  }

  function cell(label, value, good) {
    return '<div><div class="k">' + esc(label) + '</div><div class="v' + (good ? ' good' : '') + '">' +
      esc(value) + '</div></div>';
  }

  function setClock() {
    var now = new Date();
    $('clock').textContent = now.toLocaleTimeString([], { hour12: false });
  }

  function showLogin(message) {
    $('app').hidden = true;
    $('login').hidden = false;
    $('login-error').hidden = !message;
    $('login-error').textContent = message || '';
    if (refreshTimer !== null) {
      window.clearInterval(refreshTimer);
      refreshTimer = null;
    }
  }

  function showApp() {
    $('login').hidden = true;
    $('app').hidden = false;
  }

  function renderController(controller) {
    controller = controller || {};
    var net = controller.network || {};
    var addresses = controller.addresses || [];
    var ip = net.ip || addresses.join(' / ') || '—';
    $('controller-state').textContent = controller.version ? 'v' + controller.version : 'LIVE';
    $('controller-info').innerHTML =
      cell('HOST', controller.hostname || '—') +
      cell('IP', ip) +
      cell('WIFI', net.ssid || '—', !!net.ssid) +
      cell('SIGNAL', pct(net.signal_pct), num(net.signal_pct) !== null && net.signal_pct >= 50) +
      cell('GATEWAY', net.gateway || '—') +
      cell('DNS', net.dns || '—') +
      cell('UPTIME', uptime(controller.uptime_s)) +
      cell('DB', bytes(controller.db_bytes));
  }

  function deviceCard(device) {
    var latest = device.latest || {};
    var net = device.network || {};
    var status = device.status || 'offline';
    var temperature = num(latest.cpu_temp_c) !== null ? latest.cpu_temp_c : latest.gpu_temp_c;
    var meta = [String(device.category || '').toUpperCase(), device.os_name, device.os_version]
      .filter(Boolean).join(' · ');
    var localIp = net.ip || device.ip;
    var signal = num(net.signal_pct);
    var wifi;
    if (net.ssid) {
      wifi = 'WIFI ' + net.ssid + (signal !== null ? ' · ' + pct(net.signal_pct) : '');
    } else if (signal !== null) {
      wifi = 'WIFI ' + pct(net.signal_pct);
    } else if (localIp) {
      wifi = 'IP ' + localIp;
    } else {
      wifi = 'WIFI —';
    }
    var foot = '<span class="net">↓ ' + esc(rate(latest.net_down_bps)) + '</span>' +
      '<span class="net">↑ ' + esc(rate(latest.net_up_bps)) + '</span>';
    if (temperature !== null && temperature !== undefined) foot += '<span>' + esc(temp(temperature)) + '</span>';
    if (num(latest.battery_pct) !== null) foot += '<span class="' + (latest.battery_charging ? 'ok' : '') + '">' +
      esc(pct(latest.battery_pct)) + (latest.battery_charging ? ' CHG' : '') + '</span>';
    foot += '<span class="' + (net.ssid || signal !== null ? 'ok' : '') + '">' + esc(wifi) + '</span>';

    var pending = status === 'pending';
    return '<article class="device">' +
      '<div class="dev-head"><div class="left"><span class="dot ' + esc(status) + '"></span>' +
      '<span class="dev-name">' + esc(device.name) + '</span></div>' +
      '<span class="status ' + esc(status) + '">' + esc(status.toUpperCase()) + '</span></div>' +
      '<div class="dev-meta">' + esc(meta) + (localIp ? ' · ' + esc(localIp) : '') + '</div>' +
      (pending ? '<div class="dev-meta">Approve this device in the full dashboard.</div>' :
        '<div class="bars">' + bar('CPU', latest.cpu_pct) + bar('MEM', latest.ram_pct) + bar('DISK', latest.disk_pct) + '</div>') +
      '<div class="dev-foot">' + foot + '</div>' +
      '</article>';
  }

  function render(data) {
    var counts = data.counts || {};
    var devices = (data.devices || []).slice();
    $('stat-online').textContent = (counts.online || 0) + '/' + (counts.total || 0);
    $('stat-total').textContent = String(counts.total || 0);
    var alerts = num(data.alert_count) || 0;
    $('stat-alerts').textContent = String(alerts);
    $('stat-alerts').className = 'v' + (alerts ? ' warn' : ' good');

    renderController(data.controller);
    devices.sort(function (a, b) {
      var rank = { online: 0, pending: 1, offline: 2, revoked: 3 };
      var delta = (rank[a.status] || 9) - (rank[b.status] || 9);
      return delta || String(a.name).localeCompare(String(b.name));
    });
    $('device-count').textContent = devices.length + ' registered';
    $('device-list').innerHTML = devices.length
      ? devices.map(deviceCard).join('')
      : '<div class="empty">No devices yet. Pair one from the full dashboard.</div>';
    var now = new Date();
    $('updated').textContent = 'updated ' + now.toLocaleTimeString([], { hour12: false });
  }

  function api(path) {
    return fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store'
    }).then(function (response) {
      if (response.status === 401) {
        var error = new Error('authentication required');
        error.status = 401;
        throw error;
      }
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    });
  }

  function login(value) {
    return fetch('/api/v1/session', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: value })
    }).then(function (response) {
      if (response.status === 401) {
        var error = new Error('Token rejected. Check the controller token.');
        error.status = 401;
        throw error;
      }
      if (!response.ok) throw new Error('Login failed (HTTP ' + response.status + ')');
      return response.json();
    });
  }

  function load() {
    if (loading) return Promise.resolve();
    loading = true;
    return api('/api/v1/overview').then(function (data) {
      render(data);
      showApp();
    }).catch(function (error) {
      if (error.status === 401) {
        showLogin('');
      } else {
        $('updated').textContent = 'connection lost — retrying';
      }
    }).then(function () {
      loading = false;
    });
  }

  function startTimers() {
    if (refreshTimer === null) refreshTimer = window.setInterval(load, REFRESH_MS);
  }

  $('login-form').addEventListener('submit', function (event) {
    event.preventDefault();
    var value = $('token').value.trim();
    if (!value) return;
    $('login-error').hidden = true;
    login(value).then(function () {
      return load();
    }).then(function () {
      if (!$('app').hidden) {
        $('token').value = '';
        startTimers();
      } else {
        showLogin('Token rejected. Check the controller token.');
      }
    }).catch(function (error) {
      showLogin(error.message || 'Login failed.');
    });
  });

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      if (refreshTimer !== null) { window.clearInterval(refreshTimer); refreshTimer = null; }
    } else {
      load().then(function () {
        if (!$('app').hidden) startTimers();
      });
    }
  });

  setClock();
  clockTimer = window.setInterval(setClock, 1000);
  load().then(function () {
    if (!$('app').hidden) startTimers();
  });
})();
