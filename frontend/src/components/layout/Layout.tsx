import { ReactNode, useState, useEffect } from 'react'
import Sidebar from './Sidebar'
import Header from './Header'
import ProjectHeader from './ProjectHeader'

interface LayoutProps {
  children: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem('sidebar_collapsed') === 'true'
    } catch {
      return false
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem('sidebar_collapsed', String(collapsed))
    } catch {
      // ignore
    }
  }, [collapsed])

  return (
    <div className={`app-layout transition-all duration-300 ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar collapsed={collapsed} onToggleCollapse={() => setCollapsed(!collapsed)} />
      <Header />
      <main className="app-main">
        <ProjectHeader />
        {children}
      </main>
    </div>
  )
}
