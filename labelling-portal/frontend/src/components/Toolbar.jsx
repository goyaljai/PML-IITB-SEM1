import { useStore, TEAMS } from '../store/useStore'
import { api } from '../utils/api'
import { useState, useEffect, useRef } from 'react'

export default function Toolbar({ onLogout }) {
  const { user, activeTeam, setActiveTeam, eraseMode, setEraseMode, undo, redo, progress } = useStore()
  const [featJob, setFeatJob] = useState({ status: 'idle', progress: 0, total: 0, error: '' })
  const pollRef = useRef(null)

  // Poll feature extraction status while running
  useEffect(() => {
    if (featJob.status === 'running') {
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.getFeatureStatus()
          setFeatJob(s)
          if (s.status === 'done') {
            clearInterval(pollRef.current)
            // Auto-download
            const a = document.createElement('a')
            a.href = api.downloadFeaturesUrl()
            a.download = 'features.csv'
            a.click()
          } else if (s.status === 'error') {
            clearInterval(pollRef.current)
          }
        } catch {}
      }, 2000)
    }
    return () => clearInterval(pollRef.current)
  }, [featJob.status])

  async function handleExtract() {
    try {
      await api.startFeatureExtraction()
      setFeatJob({ status: 'running', progress: 0, total: 0, error: '' })
    } catch (e) {
      let msg = e.message
      try { msg = JSON.parse(msg).detail } catch {}
      alert('Feature extraction failed: ' + msg)
    }
  }

  const pct = featJob.total > 0 ? Math.round((featJob.progress / featJob.total) * 100) : 0

  return (
    <div className="bg-gray-900 border-b border-gray-700 px-3 py-2 flex items-center gap-2 flex-wrap">
      {/* Logo */}
      <span className="text-lg mr-1">🏏</span>
      <span className="text-white font-semibold text-sm mr-3">IPL Annotator</span>

      {/* Team buttons */}
      <div className="flex items-center gap-1 flex-wrap">
        {TEAMS.filter(t => t.id !== 0).map(team => (
          <button
            key={team.id}
            onClick={() => { setActiveTeam(team.id); setEraseMode(false) }}
            title={`${team.name} — label: ${team.id}, key: ${team.key}`}
            className={`px-2 py-1 rounded text-xs font-bold border transition-all ${
              activeTeam === team.id && !eraseMode
                ? 'scale-110 ring-2 ring-white'
                : 'opacity-70 hover:opacity-100'
            }`}
            style={{
              backgroundColor: team.bg,
              borderColor: activeTeam === team.id && !eraseMode ? 'white' : 'transparent',
              color: [1, 10].includes(team.id) ? '#111' : 'white',
            }}
          >
            {team.short}
            <span className="ml-1 text-xs opacity-60">[{team.id !== 10 ? team.id : '10/0'}]</span>
          </button>
        ))}
      </div>

      <div className="w-px h-6 bg-gray-600 mx-1" />

      {/* Erase */}
      <button
        onClick={() => setEraseMode(!eraseMode)}
        className={`px-2 py-1 rounded text-xs font-bold border transition-all ${
          eraseMode ? 'bg-red-600 border-white ring-2 ring-white text-white' : 'bg-gray-700 border-gray-500 text-gray-200 hover:bg-gray-600'
        }`}
        title="Erase mode (E)"
      >
        ✕ Erase [E]
      </button>

      {/* Undo/Redo */}
      <button onClick={undo} className="px-2 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 border border-gray-500" title="Undo (Ctrl+Z)">↩ Undo</button>
      <button onClick={redo} className="px-2 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 border border-gray-500" title="Redo (Ctrl+Shift+Z)">↪ Redo</button>

      <div className="flex-1" />

      {/* Progress */}
      {progress && (
        <div className="text-xs text-gray-400 mr-3 flex items-center gap-2">
          <span>
            <span className="text-green-400 font-bold">{progress.annotated}</span>
            <span className="text-gray-500">/{progress.total}</span>
            <span className="text-gray-500 ml-1">done</span>
          </span>
          <span className="text-gray-600">·</span>
          {/* Per-user breakdown */}
          {progress.per_user && Object.entries(progress.per_user).map(([username, cnt]) => (
            <span key={username}>
              <span className={username === user?.username ? 'text-blue-400 font-bold' : 'text-gray-400 font-bold'}>{cnt}</span>
              <span className="text-gray-500 ml-0.5">{username}</span>
            </span>
          ))}
        </div>
      )}

      {/* Admin export */}
      {user?.role === 'admin' && (
        <div className="flex items-center gap-1 mr-2">
          <button
            onClick={api.exportCsv}
            className="px-2 py-1 rounded text-xs bg-green-800 hover:bg-green-700 text-green-200 border border-green-600 font-medium"
          >
            ⬇ CSV
          </button>
          <button
            onClick={api.exportJson}
            className="px-2 py-1 rounded text-xs bg-green-800 hover:bg-green-700 text-green-200 border border-green-600 font-medium"
          >
            ⬇ JSON
          </button>

          {/* Feature extraction */}
          {featJob.status === 'idle' || featJob.status === 'done' || featJob.status === 'error' ? (
            <button
              onClick={handleExtract}
              className="px-2 py-1 rounded text-xs bg-purple-800 hover:bg-purple-700 text-purple-200 border border-purple-600 font-medium"
              title="Extract HSV/CM/HOG/LBP features for all annotated images"
            >
              ⚗ Features
            </button>
          ) : null}

          {featJob.status === 'running' && (
            <div className="flex items-center gap-1">
              {/* Spinner */}
              <svg className="animate-spin h-3 w-3 text-purple-400" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
              </svg>
              {/* Progress bar */}
              <div className="w-24 h-2 bg-gray-700 rounded overflow-hidden">
                <div
                  className="h-full bg-purple-500 transition-all duration-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-xs text-purple-300">{pct}%</span>
              {featJob.total > 0 && (
                <span className="text-xs text-gray-500">{featJob.progress}/{featJob.total}</span>
              )}
            </div>
          )}

          {featJob.status === 'done' && (
            <button
              onClick={() => {
                fetch(api.downloadFeaturesUrl(), {
                  headers: { Authorization: `Basic ${localStorage.getItem('creds')}` }
                })
                  .then(r => r.blob())
                  .then(blob => {
                    const a = document.createElement('a')
                    a.href = URL.createObjectURL(blob)
                    a.download = 'features.csv'
                    a.click()
                  })
              }}
              className="px-2 py-1 rounded text-xs bg-purple-700 hover:bg-purple-600 text-purple-100 border border-purple-500 font-medium"
            >
              ⬇ features.csv
            </button>
          )}

          {featJob.status === 'error' && (
            <span className="text-xs text-red-400" title={featJob.error}>⚠ Extract failed</span>
          )}
        </div>
      )}

      {/* User + logout */}
      <span className="text-xs text-gray-400">{user?.username}{user?.role === 'admin' ? ' 👑' : ''}</span>
      <button onClick={onLogout} className="px-2 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 border border-gray-600">Logout</button>
    </div>
  )
}
