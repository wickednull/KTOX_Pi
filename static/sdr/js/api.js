(function(){
  async function requestJson(path, options){
    const response = await fetch(path, options || {});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || response.statusText || 'request failed');
    }
    return data;
  }

  window.SdrApi = {
    info: () => requestJson('/api/hackrf/info'),
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
    })
  };
})();
