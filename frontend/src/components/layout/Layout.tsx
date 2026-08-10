import { ReactNode } from 'react'
import Sidebar from './Sidebar'
import Header from './Header'
import ProjectHeader from './ProjectHeader'

interface LayoutProps {
  children: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  return (
    <div className="app-layout">
      <Sidebar />
      <Header />
      <main className="app-main">
        <ProjectHeader />
        {children}
      </main>
    </div>
  )
}
