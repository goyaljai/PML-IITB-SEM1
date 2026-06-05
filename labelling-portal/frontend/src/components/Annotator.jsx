import { useEffect, useRef, useCallback, useState } from 'react'
import { useStore, TEAMS } from '../store/useStore'
import { api } from '../utils/api'
import Toolbar from './Toolbar'
import GridCanvas from './GridCanvas'
import ImageList from './ImageList'

const EMPTY_GRID = () => Array.from({ length: 8 }, () => new Array(8).fill(0))

export default function Annotator() {
  const {
    user, setUser,
    images, setImages,
    currentIndex, setCurrentIndex,
    labels, setLabels,
    activeTeam, setActiveTeam,
    eraseMode, setEraseMode,
    pushHistory, undo, redo,
    saveStatus, setSaveStatus,
    setProgress,
    imageCount, setImageCount,
  } = useStore()

  const heartbeatRef = useRef(null)
  const saveTimeout = useRef(null)
  const pendingSave = useRef(null)   // {imageId, labels} — flushed on navigate
  const loadedImageId = useRef(null)
  const [lockError, setLockError] = useState(null)

  const currentImage = images[currentIndex] || null

  // Load images on mount, then poll every 3s for other users' changes
  useEffect(() => {
    api.seed().catch(() => {})
    api.getImages().then(setImages).catch(console.error)
    api.getProgress().then(setProgress).catch(() => {})

    const poll = setInterval(() => {
      api.getImages().then(setImages).catch(() => {})
      api.getProgress().then(setProgress).catch(() => {})
    }, 3000)
    return () => clearInterval(poll)
  }, [])

  // Load annotation when image id changes
  useEffect(() => {
    if (!currentImage) return
    if (loadedImageId.current === currentImage.id) return
    loadedImageId.current = currentImage.id
    setLockError(null)
    loadAnnotationForImage(currentImage)
  }, [currentImage?.id])

  const loadAnnotationForImage = async (img) => {
    stopHeartbeat()
    setImageCount(null)
    setLabels(EMPTY_GRID())
    setSaveStatus('loading')
    try {
      await api.lockImage(img.id)
      setSaveStatus('saved')
      setLockError(null)
      startHeartbeat(img.id)
    } catch (err) {
      let msg = err.message || 'Locked'
      try { msg = JSON.parse(msg).detail } catch {}
      setLockError(msg)
      setSaveStatus('locked')
    }
    try {
      const data = await api.getAnnotation(img.id)
      setLabels(data.labels || EMPTY_GRID())
      // Auto-set count=0 for no-player images
      try {
        const num = parseInt(img.filename.replace('img_', '').replace('.jpg', ''), 10)
        const noPlayer = num >= 251 && num <= 287
        setImageCount(noPlayer ? 0 : (data.count ?? null))
      } catch {
        setImageCount(data.count ?? null)
      }
    } catch {
      setLabels(EMPTY_GRID())
    }
  }

  const startHeartbeat = (imageId) => {
    stopHeartbeat()
    heartbeatRef.current = setInterval(() => {
      api.heartbeat(imageId).catch(() => {})
    }, 30000)
  }

  const stopHeartbeat = () => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current)
      heartbeatRef.current = null
    }
  }

  const triggerSave = useCallback((newLabels, count) => {
    setSaveStatus('unsaved')
    if (saveTimeout.current) clearTimeout(saveTimeout.current)
    const cnt = count !== undefined ? count : useStore.getState().imageCount
    pendingSave.current = { imageId: currentImage?.id, labels: newLabels, count: cnt }
    saveTimeout.current = setTimeout(async () => {
      if (!currentImage) return
      pendingSave.current = null
      try {
        setSaveStatus('saving')
        await api.saveAnnotation(currentImage.id, newLabels, cnt)
        setSaveStatus('saved')
        api.getImages().then(setImages).catch(() => {})
        api.getProgress().then(setProgress).catch(() => {})
      } catch (err) {
        setSaveStatus('error')
      }
    }, 800)
  }, [currentImage])

  const handleCellPaint = useCallback((row, col) => {
    if (saveStatus === 'locked') return
    const newLabels = labels.map(r => [...r])
    const value = eraseMode ? 0 : activeTeam
    if (newLabels[row][col] === value) return
    pushHistory(labels)
    newLabels[row][col] = value
    setLabels(newLabels)
    triggerSave(newLabels)
  }, [labels, activeTeam, eraseMode, pushHistory, triggerSave, saveStatus])

  const handleRightClick = useCallback((row, col) => {
    if (saveStatus === 'locked') return
    const newLabels = labels.map(r => [...r])
    if (newLabels[row][col] === 0) return
    pushHistory(labels)
    newLabels[row][col] = 0
    setLabels(newLabels)
    triggerSave(newLabels)
  }, [labels, pushHistory, triggerSave, saveStatus])

  const flushPendingSave = async () => {
    if (!pendingSave.current) return
    const { imageId, labels, count } = pendingSave.current
    pendingSave.current = null
    if (saveTimeout.current) { clearTimeout(saveTimeout.current); saveTimeout.current = null }
    try { await api.saveAnnotation(imageId, labels, count) } catch {}
  }

  const goTo = async (index) => {
    if (index === currentIndex) return
    if (saveStatus === 'loading') return
    await flushPendingSave()
    stopHeartbeat()
    if (currentImage) api.unlockImage(currentImage.id).catch(() => {})
    loadedImageId.current = null
    setCurrentIndex(index)
  }

  const goPrev = () => currentIndex > 0 && goTo(currentIndex - 1)
  const goNext = () => currentIndex < images.length - 1 && goTo(currentIndex + 1)

  const goNextPending = () => {
    for (let i = currentIndex + 1; i < images.length; i++) {
      if (images[i].status === 'pending' && !images[i].locked_by) {
        goTo(i); return
      }
    }
  }

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === 'INPUT') return
      const key = e.key
      if (e.ctrlKey && key === 'z') {
        const before = useStore.getState().labels
        undo()
        const after = useStore.getState().labels
        if (JSON.stringify(before) !== JSON.stringify(after)) triggerSave(after)
        return
      }
      if (e.ctrlKey && e.shiftKey && key === 'Z') {
        const before = useStore.getState().labels
        redo()
        const after = useStore.getState().labels
        if (JSON.stringify(before) !== JSON.stringify(after)) triggerSave(after)
        return
      }
      if (key === ' ') { e.preventDefault(); goNext(); return }
      if (key === 'Tab') { e.preventDefault(); goNextPending(); return }
      if (key === 'ArrowRight') { goNext(); return }
      if (key === 'ArrowLeft') { goPrev(); return }
      if (key === 'e' || key === 'E') { setEraseMode(!eraseMode); return }
      const teamByKey = TEAMS.find(t => t.key === key)
      if (teamByKey && teamByKey.id !== 0) {
        setActiveTeam(teamByKey.id)
        setEraseMode(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [currentIndex, eraseMode, images, triggerSave, undo, redo])

  const isLocked = saveStatus === 'locked' || saveStatus === 'loading'

  // Detect no-player image (img_251–img_287)
  const isNoPlayer = (() => {
    if (!currentImage) return false
    try {
      const num = parseInt(currentImage.filename.replace('img_', '').replace('.jpg', ''), 10)
      return num >= 251 && num <= 287
    } catch { return false }
  })()

  const handleCountSelect = (n) => {
    if (isLocked) return
    const newCount = imageCount === n ? null : n
    setImageCount(newCount)
    triggerSave(labels, newCount)
  }

  return (
    <div className="h-screen bg-gray-950 flex flex-col overflow-hidden" style={{ userSelect: 'none' }}>
      <Toolbar onLogout={async () => {
        await flushPendingSave()
        stopHeartbeat()
        if (currentImage) api.unlockImage(currentImage.id).catch(() => {})
        localStorage.clear()
        setUser(null)
      }} />

      <div className="flex flex-1 overflow-hidden">
        <ImageList onSelect={goTo} currentIndex={currentIndex} />

        <div className="flex-1 flex flex-col items-center justify-center p-4 gap-3">
          {currentImage ? (
            <>
              {isLocked && lockError && (
                <div className="bg-yellow-900/60 border border-yellow-600 text-yellow-300 px-4 py-2 rounded-lg text-sm flex items-center gap-3">
                  <span>🔒 {lockError} — view only</span>
                  {user?.role === 'admin' && (
                    <button
                      onClick={async () => {
                        await api.forceUnlock(currentImage.id)
                        loadedImageId.current = null
                        loadAnnotationForImage(currentImage)
                      }}
                      className="px-2 py-0.5 rounded text-xs bg-yellow-700 hover:bg-yellow-600 text-white border border-yellow-500 font-medium"
                    >Force unlock</button>
                  )}
                </div>
              )}
              <div className="flex items-stretch gap-3">
                <GridCanvas
                  key={currentImage.id}
                  imageId={currentImage.id}
                  onCellPaint={handleCellPaint}
                  onRightClick={handleRightClick}
                  readonly={isLocked}
                />
                <CountSelector
                  count={imageCount}
                  isNoPlayer={isNoPlayer}
                  disabled={isLocked}
                  onSelect={handleCountSelect}
                />
              </div>
            </>
          ) : (
            <div className="text-gray-500 text-lg">
              {images.length === 0 ? 'Loading images…' : 'Select an image from the list'}
            </div>
          )}
        </div>
      </div>

      {/* Bottom bar */}
      <div className="bg-gray-900 border-t border-gray-700 px-4 py-2 flex items-center gap-3 text-sm">
        <button onClick={goPrev} disabled={currentIndex === 0}
          className="px-3 py-1 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded text-white">
          ← Prev
        </button>
        <button onClick={goNext} disabled={currentIndex >= images.length - 1}
          className="px-3 py-1 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded text-white">
          Next →
        </button>
        <button onClick={goNextPending}
          className="px-3 py-1 bg-blue-800 hover:bg-blue-700 rounded text-blue-200 font-medium"
          title="Jump to next unannotated image (Tab)">
          ⏭ Next Pending [Tab]
        </button>

        <div className="flex-1 text-center text-gray-500 text-xs font-mono truncate">
          {currentImage?.filename}
        </div>

        <span className="text-gray-400">{currentIndex + 1} / {images.length}</span>
        <SaveBadge status={saveStatus} />
      </div>
    </div>
  )
}

function SaveBadge({ status }) {
  const map = { saved: 'text-green-400', saving: 'text-yellow-400', unsaved: 'text-orange-400', error: 'text-red-400', locked: 'text-gray-500' }
  const label = { saved: '✓ Saved', saving: '⟳ Saving…', unsaved: '● Unsaved', error: '✗ Error', locked: '🔒 View only' }
  return <span className={`text-xs font-medium ${map[status] || 'text-gray-400'}`}>{label[status] || ''}</span>
}

function CountSelector({ count, isNoPlayer, disabled, onSelect }) {
  const numbers = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20]

  return (
    <div className="flex flex-col gap-1 justify-center" style={{ minWidth: 96 }}>
      <div className="text-xs text-gray-500 text-center mb-1 font-medium uppercase tracking-wide">
        # players
      </div>
      <div className="grid grid-cols-2 gap-1">
        {numbers.map(n => {
          const isSelected = count === n
          return (
            <button
              key={n}
              onClick={() => onSelect(n)}
              disabled={disabled}
              title={n === 0 ? 'No player' : `${n} player${n > 1 ? 's' : ''}`}
              className={`w-10 h-8 rounded text-sm font-bold border-2 transition-all ${
                isSelected
                  ? 'bg-blue-600 border-blue-400 text-white ring-2 ring-blue-300 scale-105'
                  : disabled
                  ? 'bg-gray-800 border-gray-700 text-gray-600 cursor-not-allowed'
                  : 'bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700 hover:border-gray-400 hover:text-white'
              }`}
            >
              {n}
            </button>
          )
        })}
      </div>
      {!isNoPlayer && count === null && (
        <div className="text-xs text-center mt-1 font-medium text-orange-400" title="Select player count">
          ?
        </div>
      )}
    </div>
  )
}
