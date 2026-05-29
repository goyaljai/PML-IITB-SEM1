import { useEffect } from 'react'
import { useStore } from './store/useStore'
import Login from './components/Login'
import Annotator from './components/Annotator'

export default function App() {
  const { user, setUser } = useStore()

  useEffect(() => {
    const saved = localStorage.getItem('user')
    if (saved) setUser(JSON.parse(saved))
  }, [])

  if (!user) return <Login />
  return <Annotator />
}
