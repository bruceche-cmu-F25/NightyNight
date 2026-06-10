import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { accessToken, loading } = useAuth()
  if (loading) return (
    <div className="root" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100dvh' }}>
      <p style={{ color: '#7fa8c8' }}>Loading…</p>
    </div>
  )
  if (!accessToken) return <Navigate to="/login" replace />
  return <>{children}</>
}
