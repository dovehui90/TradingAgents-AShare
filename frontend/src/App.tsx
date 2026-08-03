import { BrowserRouter, Navigate, Routes, Route } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { SpeedInsights } from '@vercel/speed-insights/react'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Analysis from './pages/Analysis'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import Portfolio from './pages/Portfolio'
import TrackingBoard from './pages/TrackingBoard'
import Accuracy from './pages/Accuracy'
import Login from './pages/Login'
import Sponsor from './pages/Sponsor'
import Thanks from './pages/Thanks'
import Admin from './pages/Admin'
import Briefing from './pages/Briefing'
import Screener from './pages/Screener'
import DailyReview from './pages/DailyReview'
import { useAuthStore } from './stores/authStore'

function useIsMobile() {
  const [m, setM] = useState(() => typeof window !== 'undefined' && window.innerWidth < 768)
  useEffect(() => {
    const h = () => setM(window.innerWidth < 768)
    window.addEventListener('resize', h)
    return () => window.removeEventListener('resize', h)
  }, [])
  return m
}

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, hydrated, hydrate } = useAuthStore()

  useEffect(() => {
    if (!hydrated) void hydrate()
  }, [hydrated, hydrate])

  if (!hydrated) {
    return <div className="min-h-screen flex items-center justify-center text-slate-500">加载中...</div>
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return children
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  const { user } = useAuthStore()
  if (!user?.is_admin) return <Navigate to="/" replace />
  return children
}

function App() {
  const isMobile = useIsMobile()

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/sponsor" element={<Sponsor />} />
        <Route path="/thanks" element={<Thanks />} />
        <Route
          path="*"
          element={
            <RequireAuth>
              <Layout>
                <Routes>
                  <Route path="/analysis" element={<Analysis />} />
                  <Route path="/daily-review" element={<DailyReview />} />
                  <Route path="/screener" element={<RequireAdmin><Screener /></RequireAdmin>} />
                  <Route path="/briefing" element={<RequireAdmin><Briefing /></RequireAdmin>} />
                  {!isMobile && (
                    <>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/tracking-board" element={<TrackingBoard />} />
                      <Route path="/accuracy" element={<Accuracy />} />
                      <Route path="/reports" element={<Reports />} />
                      <Route path="/portfolio" element={<Portfolio />} />
                      <Route path="/settings" element={<RequireAdmin><Settings /></RequireAdmin>} />
                      <Route path="/admin" element={<Admin />} />
                    </>
                  )}
                  <Route path="*" element={<Navigate to="/analysis" replace />} />
                </Routes>
              </Layout>
            </RequireAuth>
          }
        />
      </Routes>
      <SpeedInsights />
    </BrowserRouter>
  )
}

export default App
