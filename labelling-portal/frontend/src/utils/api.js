const BASE = '/api'

function authHeader() {
  const creds = localStorage.getItem('creds')
  return creds ? { Authorization: `Basic ${creds}` } : {}
}

async function request(path, opts = {}) {
  const res = await fetch(BASE + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...authHeader(), ...(opts.headers || {}) },
  })
  if (res.status === 401) {
    localStorage.removeItem('creds')
    localStorage.removeItem('user')
    window.location.reload()
  }
  if (!res.ok) throw new Error(await res.text())
  return res
}

export const api = {
  login: async (username, password) => {
    const creds = btoa(`${username}:${password}`)
    const res = await fetch(`${BASE}/login`, {
      headers: { Authorization: `Basic ${creds}` },
    })
    if (!res.ok) throw new Error('Invalid credentials')
    const user = await res.json()
    localStorage.setItem('creds', creds)
    localStorage.setItem('user', JSON.stringify(user))
    return user
  },

  seed: () => request('/seed', { method: 'POST' }),

  getImages: () => request('/images').then(r => r.json()),

  getImageUrl: (id) => `${BASE}/images/${id}/file`,

  getProgress: () => request('/images/progress').then(r => r.json()),

  lockImage: (id) => request(`/images/${id}/lock`, { method: 'POST' }),
  unlockImage: (id) => request(`/images/${id}/unlock`, { method: 'POST' }),
  heartbeat: (id) => request(`/images/${id}/heartbeat`, { method: 'POST' }),

  getAnnotation: (imageId) => request(`/annotations/${imageId}`).then(r => r.json()),

  saveAnnotation: (imageId, labels, count) =>
    request(`/annotations/${imageId}`, {
      method: 'POST',
      body: JSON.stringify({ labels, count: count ?? null }),
    }),

  exportCsv: () => {
    fetch(`${BASE}/export/csv`, { headers: authHeader() })
      .then(r => r.blob())
      .then(blob => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = 'annotations.csv'
        a.click()
      })
  },

  exportJson: () => {
    fetch(`${BASE}/export/json`, { headers: authHeader() })
      .then(r => r.blob())
      .then(blob => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = 'annotations.json'
        a.click()
      })
  },

  forceUnlock: (id) => request(`/images/${id}/force-unlock`, { method: 'POST' }),

  getStats: () => request('/stats').then(r => r.json()),

  startFeatureExtraction: () => request('/export/features', { method: 'POST' }),
  getFeatureStatus: () => request('/export/features/status').then(r => r.json()),
  downloadFeaturesUrl: () => `${BASE}/export/features/download`,
}
