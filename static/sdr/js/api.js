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
    readiness: (payload) => requestJson('/api/hackrf/readiness', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
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
    diagnostics: () => requestJson('/api/diagnostics'),
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
    receiverBookmarks: (params) => {
      const query = new URLSearchParams(params || {}).toString();
      return requestJson(`/api/receiver/bookmarks${query ? `?${query}` : ''}`);
    },
    receiverBookmarkAdd: (payload) => requestJson('/api/receiver/bookmarks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverBookmarksImport: (payload) => requestJson('/api/receiver/bookmarks/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverBookmarksExportUrl: () => withBase('/api/receiver/bookmarks.json'),
    receiverBookmarkDelete: (id) => requestJson(`/api/receiver/bookmarks/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    receiverActivity: (params) => {
      const query = new URLSearchParams(params || {}).toString();
      return requestJson(`/api/receiver/activity${query ? `?${query}` : ''}`);
    },
    receiverAlerts: (params) => {
      const query = new URLSearchParams(params || {}).toString();
      return requestJson(`/api/receiver/alerts${query ? `?${query}` : ''}`);
    },
    receiverAlertRuleAdd: (payload) => requestJson('/api/receiver/alerts/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverAlertRuleDelete: (id) => requestJson(`/api/receiver/alerts/rules/${encodeURIComponent(id)}`, { method: 'DELETE' }),
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
    }),
    trunkingAgreement: () => requestJson('/api/trunking/agreement'),
    trunkingAcceptAgreement: (payload) => requestJson('/api/trunking/agreement', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    trunkingProfiles: () => requestJson('/api/trunking/profiles'),
    trunkingAddProfile: (payload) => requestJson('/api/trunking/profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    trunkingProfilesImport: (payload) => requestJson('/api/trunking/profiles/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    trunkingDeleteProfile: (id) => requestJson(`/api/trunking/profiles/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    trunkingStart: (payload) => requestJson('/api/trunking/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    trunkingStop: () => requestJson('/api/trunking/stop', { method: 'POST' }),
    trunkingStatus: () => requestJson('/api/trunking/status'),
    trunkingEvents: (params) => {
      const query = new URLSearchParams(params || {}).toString();
      return requestJson(`/api/trunking/events${query ? `?${query}` : ''}`);
    },
    trunkingSummary: () => requestJson('/api/trunking/summary'),
    trunkingAliases: () => requestJson('/api/trunking/aliases'),
    trunkingAliasUpsert: (payload) => requestJson('/api/trunking/aliases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    trunkingAliasesImport: (payload) => requestJson('/api/trunking/aliases/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    trunkingAddEvent: (payload) => requestJson('/api/trunking/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    decoderStatus: () => requestJson('/api/decoders/status'),
    decoderPlan: (payload) => requestJson('/api/decoders/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    decoderEvents: (params) => {
      const query = new URLSearchParams(params || {}).toString();
      return requestJson(`/api/decoders/events${query ? `?${query}` : ''}`);
    },
    decoderAddEvent: (payload) => requestJson('/api/decoders/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    })
  };
})();
