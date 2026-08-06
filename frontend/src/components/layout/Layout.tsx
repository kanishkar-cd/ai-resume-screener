import { ReactNode } from 'react'
import Sidebar from './Sidebar'
import Header from './Header'

interface LayoutProps {
  children: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  return (
    <div className="app-layout">
      <Sidebar />
      <Header />
      <main className="app-main">
        {children}
      </main>
    </div>
  )
}
