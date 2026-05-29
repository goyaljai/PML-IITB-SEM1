import { useState, useCallback, useRef, useEffect } from 'react'
import { useStore, TEAMS } from '../store/useStore'
import { api } from '../utils/api'

const COLS = 8
const ROWS = 8
const IMG_W = 800
const IMG_H = 600
const CELL_W = IMG_W / COLS
const CELL_H = IMG_H / ROWS

export default function GridCanvas({ imageId, onCellPaint, onRightClick, readonly }) {
  const { labels } = useStore()
  const [hovered, setHovered] = useState(null)
  const [imgLoaded, setImgLoaded] = useState(false)
  const [imgError, setImgError] = useState(false)
  const isPainting = useRef(false)
  const lastPainted = useRef(null)
  const imgRef = useRef(null)

  // Reset load state when imageId changes
  useEffect(() => {
    setImgLoaded(false)
    setImgError(false)
    // Force reload if already cached but broken
    if (imgRef.current) {
      imgRef.current.src = ''
      imgRef.current.src = api.getImageUrl(imageId) + '?t=' + imageId
    }
  }, [imageId])

  const paintCell = useCallback((row, col) => {
    const key = `${row}-${col}`
    if (key === lastPainted.current) return
    lastPainted.current = key
    onCellPaint(row, col)
  }, [onCellPaint])

  const getCellFromEvent = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    const col = Math.floor(x / CELL_W)
    const row = Math.floor(y / CELL_H)
    if (row < 0 || row >= ROWS || col < 0 || col >= COLS) return null
    return { row, col }
  }

  const handleMouseDown = (e) => {
    if (readonly || e.button === 2) return
    e.preventDefault()
    isPainting.current = true
    const cell = getCellFromEvent(e)
    if (cell) paintCell(cell.row, cell.col)
  }

  const handleMouseMove = (e) => {
    const cell = getCellFromEvent(e)
    setHovered(cell)
    if (isPainting.current && !readonly && cell) paintCell(cell.row, cell.col)
  }

  const handleMouseUp = () => {
    isPainting.current = false
    lastPainted.current = null
  }

  const handleContextMenu = (e) => {
    e.preventDefault()
    if (readonly) return
    const cell = getCellFromEvent(e)
    if (cell) onRightClick(cell.row, cell.col)
  }

  const imgSrc = api.getImageUrl(imageId) + '?id=' + imageId

  return (
    <div
      style={{
        position: 'relative',
        width: IMG_W,
        height: IMG_H,
        cursor: readonly ? 'not-allowed' : 'crosshair',
        userSelect: 'none',
        borderRadius: 8,
        overflow: 'hidden',
        border: readonly ? '2px solid rgba(202,138,4,0.5)' : '1px solid rgba(75,85,99,1)',
        boxShadow: '0 25px 50px -12px rgba(0,0,0,0.8)',
        flexShrink: 0,
        backgroundColor: '#111',
      }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={() => { setHovered(null); handleMouseUp() }}
      onContextMenu={handleContextMenu}
    >
      {/* Loading indicator */}
      {!imgLoaded && !imgError && (
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#6b7280', fontSize: 14,
        }}>
          Loading…
        </div>
      )}

      {/* Error state */}
      {imgError && (
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          color: '#ef4444', fontSize: 14, gap: 8,
        }}>
          <div>⚠ Image failed to load</div>
          <button
            onClick={() => { setImgError(false); setImgLoaded(false); if (imgRef.current) { imgRef.current.src = imgSrc + '&retry=' + Date.now() } }}
            style={{ padding: '4px 12px', background: '#374151', border: '1px solid #6b7280', borderRadius: 6, color: 'white', cursor: 'pointer', fontSize: 12 }}
          >Retry</button>
        </div>
      )}

      {/* The actual image */}
      <img
        ref={imgRef}
        src={imgSrc}
        width={IMG_W}
        height={IMG_H}
        onLoad={() => setImgLoaded(true)}
        onError={() => setImgError(true)}
        style={{
          display: 'block',
          pointerEvents: 'none',
          opacity: imgLoaded ? 1 : 0,
          transition: 'opacity 0.15s',
        }}
        draggable={false}
        alt=""
      />

      {/* Grid overlay — only when image loaded */}
      {imgLoaded && (
        <div style={{ position: 'absolute', top: 0, left: 0, width: IMG_W, height: IMG_H }}>
          {Array.from({ length: ROWS }, (_, row) =>
            Array.from({ length: COLS }, (_, col) => {
              const label = labels[row]?.[col] ?? 0
              const team = label !== 0 ? TEAMS.find(t => t.id === label) : null
              const isHovered = hovered?.row === row && hovered?.col === col
              const x = col * CELL_W
              const y = row * CELL_H

              return (
                <div key={`${row}-${col}`} style={{
                  position: 'absolute', left: x, top: y,
                  width: CELL_W, height: CELL_H,
                  boxSizing: 'border-box',
                  border: '1px solid rgba(255,255,255,0.18)',
                  backgroundColor: team
                    ? team.color
                    : isHovered && !readonly
                    ? 'rgba(255,255,255,0.1)'
                    : 'transparent',
                  outline: isHovered && !readonly ? '2px solid rgba(255,255,255,0.65)' : 'none',
                  outlineOffset: '-2px',
                }}>
                  {team && (
                    <span style={{
                      position: 'absolute', top: 2, left: 3,
                      fontSize: 11, fontWeight: 'bold', color: 'white',
                      textShadow: '0 0 4px black, 0 0 6px black',
                      pointerEvents: 'none', lineHeight: 1,
                    }}>{team.short}</span>
                  )}
                  <span style={{
                    position: 'absolute', bottom: 1, right: 2,
                    fontSize: 9, color: 'rgba(255,255,255,0.3)',
                    pointerEvents: 'none', lineHeight: 1,
                  }}>{row * COLS + col + 1}</span>
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
