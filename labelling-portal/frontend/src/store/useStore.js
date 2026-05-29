import { create } from 'zustand'

export const TEAMS = [
  { id: 0,  name: 'Empty', short: '—',    color: 'rgba(0,0,0,0)',           bg: '#374151', key: null },
  { id: 1,  name: 'CSK',   short: 'CSK',  color: 'rgba(255,215,0,0.55)',    bg: '#FFD700', key: '1' },
  { id: 2,  name: 'DC',    short: 'DC',   color: 'rgba(0,0,139,0.55)',      bg: '#00008B', key: '2' },
  { id: 3,  name: 'GT',    short: 'GT',   color: 'rgba(27,42,74,0.65)',     bg: '#1B2A4A', key: '3' },
  { id: 4,  name: 'KKR',   short: 'KKR',  color: 'rgba(58,34,93,0.65)',     bg: '#3A225D', key: '4' },
  { id: 5,  name: 'LSG',   short: 'LSG',  color: 'rgba(0,166,147,0.55)',    bg: '#00A693', key: '5' },
  { id: 6,  name: 'MI',    short: 'MI',   color: 'rgba(0,75,160,0.55)',     bg: '#004BA0', key: '6' },
  { id: 7,  name: 'PBKS',  short: 'PBKS', color: 'rgba(237,27,36,0.55)',    bg: '#ED1B24', key: '7' },
  { id: 8,  name: 'RR',    short: 'RR',   color: 'rgba(234,26,127,0.55)',   bg: '#EA1A7F', key: '8' },
  { id: 9,  name: 'RCB',   short: 'RCB',  color: 'rgba(200,0,0,0.55)',      bg: '#C80000', key: '9' },
  { id: 10, name: 'SRH',   short: 'SRH',  color: 'rgba(247,167,33,0.65)',   bg: '#F7A721', key: '0' },
]

const EMPTY_GRID = () => Array.from({ length: 8 }, () => new Array(8).fill(0))

export const useStore = create((set, get) => ({
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  setUser: (u) => set({ user: u }),

  images: [],
  setImages: (images) => set({ images }),

  currentIndex: 0,
  setCurrentIndex: (i) => set({ currentIndex: i }),

  labels: EMPTY_GRID(),
  setLabels: (labels) => set({ labels }),
  setCell: (row, col, value) => {
    const labels = get().labels.map(r => [...r])
    labels[row][col] = value
    set({ labels })
  },

  activeTeam: 1,
  setActiveTeam: (t) => set({ activeTeam: t }),

  eraseMode: true,
  setEraseMode: (v) => set({ eraseMode: v }),

  history: [],
  pushHistory: (labels) => {
    const h = get().history.slice(-30)
    set({ history: [...h, labels.map(r => [...r])] })
  },
  undo: () => {
    const h = get().history
    if (!h.length) return
    const prev = h[h.length - 1]
    set({ labels: prev.map(r => [...r]), history: h.slice(0, -1) })
  },

  future: [],
  pushFuture: (labels) => {
    set({ future: [...get().future.slice(-30), labels.map(r => [...r])] })
  },
  redo: () => {
    const f = get().future
    if (!f.length) return
    const next = f[f.length - 1]
    get().pushHistory(get().labels)
    set({ labels: next.map(r => [...r]), future: f.slice(0, -1) })
  },

  saveStatus: 'saved',
  setSaveStatus: (s) => set({ saveStatus: s }),

  progress: null,
  setProgress: (p) => set({ progress: p }),

  imageCount: null,
  setImageCount: (c) => set({ imageCount: c }),
}))
