(function(){
  function basePath(){
    const path = window.location.pathname || '/';
    return path.startsWith('/sdr') ? '/sdr' : '';
  }

  function withBase(path){
    return `${basePath()}${path}`;
  }

  async function requestJson(path, options){
    const response = await fetch(withBase(path), options || {});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || response.statusText || 'request failed');
    }
    return data;
  }

  window.SdrApiBasePath = basePath;
  window.SdrApiUrl = withBase;
  window.SdrApi = {
    info: () => requestJson('/api/hackrf/info'),
    connect: () => requestJson('/api/hackrf/connect', { method: 'POST' }),
    test: (payload) => requestJson('/api/hackrf/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    serialPorts: () => requestJson('/api/serial/ports'),
    serialProbe: (payload) => requestJson('/api/serial/probe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverStart: (payload) => requestJson('/api/receiver/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverStop: () => requestJson('/api/receiver/stop', { method: 'POST' }),
    receiverStatus: () => requestJson('/api/receiver/status'),
    receiverFrame: (payload) => requestJson('/api/receiver/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverAudio: (payload) => requestJson('/api/receiver/audio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverScan: (payload) => requestJson('/api/receiver/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverBookmarks: () => requestJson('/api/receiver/bookmarks'),
    receiverBookmarkAdd: (payload) => requestJson('/api/receiver/bookmarks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverBookmarkDelete: (id) => requestJson(`/api/receiver/bookmarks/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    presets: () => requestJson('/api/hackrf/presets'),
    captures: () => requestJson('/api/hackrf/captures'),
    deleteCapture: (id) => requestJson(`/api/hackrf/captures/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    sweep: (payload) => requestJson('/api/hackrf/sweep', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }),
    capture: (payload) => requestJson('/api/hackrf/capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }),
    waterfallRow: (payload) => requestJson('/api/hackrf/waterfall-row', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }),
    demodulate: (payload) => requestJson('/api/hackrf/demodulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    })
  };
})();
