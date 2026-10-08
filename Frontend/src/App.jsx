import { useState, useEffect, useCallback, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './lib/AuthContext'
import { canDo } from './lib/auth'
import { ToastProvider } from './components/Toast'
import ErrorBoundary from './components/ErrorBoundary'
import Sidebar from './components/Sidebar'
import Tour, { hasTourBeenSeen, markTourDone } from './components/Tour'
import { Spinner } from './components/UI'

// Lazy-load all pages
const Dashboard    = lazy(() => import('./pages/Dashboard'))
const Inventory    = lazy(() => import('./pages/Inventory'))
const PR           = lazy(() => import('./pages/PR'))
const PO           = lazy(() => import('./pages/PO'))
const GRN          = lazy(() => import('./pages/GRN'))
const Returns      = lazy(() => import('./pages/Returns'))
const Import       = lazy(() => import('./pages/Import'))
const Admin        = lazy(() => import('./pages/Admin'))
const ApiHealth    = lazy(() => import('./pages/ApiHealth'))
const Items        = lazy(() => import('./pages/Items'))
const HKMaster     = lazy(() => import('./pages/HKMaster'))
const Vendors      = lazy(() => import('./pages/Vendors'))
const Locations    = lazy(() => import('./pages/Locations'))
const Budget       = lazy(() => import('./pages/Budget'))
const Issuance     = lazy(() => import('./pages/Issuance'))
const Profile      = lazy(() => import('./pages/Profile'))
const Login        = lazy(() => import('./pages/Login'))
const Signup       = lazy(() => import('./pages/Signup'))
const BudgetOverview = lazy(() => import('./pages/BudgetOverview'))
const MasterGroups   = lazy(() => import('./pages/MasterGroups'))

const BudgetCalc     = () => <Budget defaultTab="calculator" />
const BudgetVariance = () => <Budget defaultTab="variance" />
const BudgetNorms    = () => <Budget defaultTab="norms" />
const BudgetForecast = () => <Budget defaultTab="forecast" />

// Expose tour launcher globally so Profile page can trigger it
export const tourBus = { onLaunch: null }

const PageSpinner = () => (
  <div className="page-content"><Spinner /></div>
)

function ProtectedLayout() {
  const { user } = useAuth()
  const [showTour, setShowTour] = useState(false)

  // Auto-launch for first-time users
  useEffect(() => {
    if (user && !hasTourBeenSeen(user.id)) {
      const t = setTimeout(() => setShowTour(true), 800)
      return () => clearTimeout(t)
    }
  }, [user])

  // Allow Profile page to re-launch tour
  useEffect(() => {
    tourBus.onLaunch = () => setShowTour(true)
    return () => { tourBus.onLaunch = null }
  }, [])

  // Keyboard: Escape skips tour
  const handleKey = useCallback((e) => {
    if (!showTour) return
    if (e.key === 'Escape') { markTourDone(user?.id); setShowTour(false) }
  }, [showTour, user])

  useEffect(() => {
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [handleKey])

  return (
    <>
      <Sidebar />
      <div className="app-layout">
        <ErrorBoundary>
          <Suspense fallback={<PageSpinner />}>
            <Routes>
              <Route path="/"                    element={<Dashboard />} />
              <Route path="/inventory"           element={<Inventory />} />
              <Route path="/procurement/pr"      element={<PR />} />
              <Route path="/procurement/po"      element={<PO />} />
              <Route path="/procurement/grn"     element={<GRN />} />
              <Route path="/returns"             element={<Returns />} />
              <Route path="/import"              element={<Import />} />
              <Route path="/issuance"            element={<Issuance />} />
              <Route path="/masters/items"          element={<Items />} />
              <Route path="/masters/master-groups" element={<MasterGroups />} />
              <Route path="/masters/hk"            element={<HKMaster />} />
              <Route path="/masters/vendors"       element={<Vendors />} />
              <Route path="/locations"           element={<Locations />} />
              <Route path="/budget"              element={<BudgetOverview />} />
              <Route path="/budget/calculator"   element={<BudgetCalc />} />
              <Route path="/budget/variance"     element={<BudgetVariance />} />
              <Route path="/budget/norms"        element={<BudgetNorms />} />
              <Route path="/budget/forecast"     element={<BudgetForecast />} />
              <Route path="/profile"             element={<Profile />} />
              <Route path="/admin"               element={canDo(user?.role, "admin") ? <Admin /> : <Navigate to="/" replace />} />
              <Route path="/admin/health"        element={canDo(user?.role, "super_admin") ? <ApiHealth /> : <Navigate to="/" replace />} />
              <Route path="*"                    element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </div>

      {showTour && (
        <Tour user={user} onDone={() => { markTourDone(user?.id); setShowTour(false) }} />
      )}
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <AppRoutes />
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

function AppRoutes() {
  const { user, loading } = useAuth()

  if (loading) return (
    <div style={{ minHeight:'100vh', display:'flex', alignItems:'center', justifyContent:'center', background:'#0d0f1a' }}>
      <div style={{ textAlign:'center' }}>
        <div style={{ width:48, height:48, borderRadius:12, background:'linear-gradient(135deg,#f0a500,#e85d04)', display:'flex', alignItems:'center', justifyContent:'center', color:'white', fontFamily:"'Fraunces',serif", fontWeight:800, fontSize:22, margin:'0 auto 16px' }}>G</div>
        <Spinner />
      </div>
    </div>
  )

  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route path="/login"  element={user ? <Navigate to="/" replace /> : <Login />} />
        <Route path="/signup" element={user ? <Navigate to="/" replace /> : <Signup />} />
        <Route path="*"       element={user ? <ProtectedLayout /> : <Navigate to="/login" replace />} />
      </Routes>
    </Suspense>
  )
}