import { useStore } from '../store/useStore'

const STATUS_COLORS = {
  done:    'bg-green-800/60 border-green-600 text-green-300',
  pending: 'bg-gray-800 border-gray-600 text-gray-300',
  locked:  'bg-yellow-900/60 border-yellow-600 text-yellow-300',
}

export default function ImageList({ onSelect, currentIndex }) {
  const { images, user } = useStore()

  return (
    <div className="w-56 bg-gray-900 border-r border-gray-700 flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-gray-700 text-xs text-gray-400 font-medium uppercase tracking-wide">
        Images ({images.length})
      </div>
      <div className="flex-1 overflow-y-auto">
        {images.map((img, idx) => {
          const isCurrent = idx === currentIndex
          const isLockedByOther = img.locked_by && img.locked_by !== user?.username
          const isDoneByOther = img.status === 'done' && img.annotator && img.annotator !== user?.username
          const isDoneByme = img.status === 'done' && img.annotator === user?.username

          let statusClass = 'bg-gray-800 border-gray-700'
          let badge = null
          if (isDoneByOther) {
            statusClass = 'bg-green-900/40 border-green-800'
            badge = <span className="text-xs text-green-400 ml-1">✓ {img.annotator}</span>
          } else if (isDoneByme) {
            statusClass = 'bg-green-900/60 border-green-700'
            badge = <span className="text-xs text-green-300 ml-1">✓ me</span>
          } else if (isLockedByOther) {
            statusClass = 'bg-yellow-900/30 border-yellow-800'
            badge = <span className="text-xs text-yellow-400 ml-1">✏ {img.locked_by}</span>
          }

          return (
            <button
              key={img.id}
              onClick={() => onSelect(idx)}
              className={`w-full text-left px-3 py-1.5 border-b text-xs transition-all hover:bg-gray-700 ${statusClass} ${
                isCurrent ? 'ring-1 ring-inset ring-blue-400 bg-blue-900/30' : ''
              }`}
            >
              <div className="flex items-center justify-between gap-1">
                <span className={`font-mono truncate ${isCurrent ? 'text-blue-300' : 'text-gray-300'}`}>
                  {idx + 1}. {img.filename.slice(0, 16)}…
                </span>
              </div>
              {badge && <div className="mt-0.5">{badge}</div>}
            </button>
          )
        })}
      </div>
    </div>
  )
}
