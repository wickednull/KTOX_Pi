(function(){
  const RJShared = {
    getApiUrl(path, params = {}, loc){
      const locationRef = loc || window.location;
      const qs = new URLSearchParams(params).toString();
      return `${locationRef.origin}${path}${qs ? `?${qs}` : ''}`;
    },

    getWsUrlCandidates(loc){
      const locationRef = loc || window.location;
      const p = new URLSearchParams(locationRef.search || '');
      const explicit = String(p.get('ws') || '').trim();
      if (explicit){
        return [explicit];
      }

      const host = locationRef.hostname || 'raspberrypi.local';
      const explicitPort = String(p.get('port') || p.get('wsport') || '').trim();
      const originPort = String(locationRef.port || '').trim();
      const port = explicitPort || originPort || '8765';
      const sameOriginWs = `${locationRef.origin.replace(/^https?:/, locationRef.protocol === 'https:' ? 'wss:' : 'ws:')}/ws`;

      if (locationRef.protocol === 'https:'){
        // iOS PWA/Safari can stall for a long time on unreachable fallback endpoints.
        // Prefer the reverse-proxied same-origin websocket path only.
        return [
          `${locationRef.origin.replace(/^https:/, 'wss:')}/ws`,
        ];
      }
      if (!explicitPort && originPort){
        return [
          sameOriginWs,
          `ws://${host}:8765/`.replace(/\/\/\//, '//'),
        ];
      }
      return [
        sameOriginWs,
        `ws://${host}:${port}/`.replace(/\/\/\//, '//'),
      ];
    },

    getWsUrl(loc){
      const locationRef = loc || window.location;
      const p = new URLSearchParams(locationRef.search || '');
      const explicit = String(p.get('ws') || '').trim();
      if (explicit){
        return explicit;
      }

      if (locationRef.protocol === 'https:'){
        return `${locationRef.origin.replace(/^https:/, 'wss:')}/ws`;
      }

      const host = locationRef.hostname || 'raspberrypi.local';
      const explicitPort = String(p.get('port') || p.get('wsport') || '').trim();
      const port = explicitPort || '8765';
      return `ws://${host}:${port}/`.replace(/\/\/\//, '//');
    },

    saveToken(storageKey, token){
      const value = String(token || '').trim();
      try{
        if (value){
          sessionStorage.setItem(storageKey, value);
          localStorage.setItem(storageKey, value);
        } else {
          sessionStorage.removeItem(storageKey);
          localStorage.removeItem(storageKey);
        }
      }catch{}
      return value;
    },

    loadToken(storageKey){
      try{
        // iOS PWA fix: localStorage first (survives PWA restart)
        return String(localStorage.getItem(storageKey) || sessionStorage.getItem(storageKey) || '').trim();
      }catch{
        try{
          return String(localStorage.getItem(storageKey) || '').trim();
        }catch{
          return '';
        }
      }
    },

    migrateTokenFromUrl(storageKey, urlParam = 'token'){
      try{
        const u = new URL(window.location.href);
        const token = String(u.searchParams.get(urlParam) || '').trim();
        if (!token) return '';
        const saved = this.saveToken(storageKey, token);
        u.searchParams.delete(urlParam);
        window.history.replaceState({}, '', u.toString());
        return saved;
      }catch{
        return '';
      }
    },

    authHeaders(token, extra){
      const headers = Object.assign({}, extra || {});
      const authToken = String(token || '').trim();
      if (authToken){
        headers.Authorization = `Bearer ${authToken}`;
      }
      return headers;
    },

    async fetchJson(url, options = {}){
      const res = await fetch(url, options);
      let data = null;
      try { data = await res.json(); } catch {}
      return { res, data };
    },

    async fetchBootstrapStatus(getApiUrl){
      try{
        const { res, data } = await this.fetchJson(getApiUrl('/api/auth/bootstrap-status'), { cache: 'no-store' });
        return !!(res.ok && data && data.initialized);
      }catch{
        return true;
      }
    },

    async fetchAuthMe(getApiUrl, token){
      try{
        const { res, data } = await this.fetchJson(getApiUrl('/api/auth/me'), {
          cache: 'no-store',
          credentials: 'include',
          headers: this.authHeaders(token, {}),
        });
        if (!res.ok) return null;
        return data && data.authenticated ? data : null;
      }catch{
        return null;
      }
    },

    async refreshWsTicket(getApiUrl, token){
      if (token) return '';
      try{
        const { res, data } = await this.fetchJson(getApiUrl('/api/auth/ws-ticket'), {
          method: 'POST',
          credentials: 'include',
        });
        if (res.ok && data && data.ticket){
          return String(data.ticket);
        }
      }catch{}
      return '';
    },
  };

  window.RJShared = RJShared;
})();
