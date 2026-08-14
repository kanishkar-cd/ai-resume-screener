import { motion } from 'framer-motion'
import { useLocation, useNavigate } from 'react-router-dom'
import { Home, UserRound } from 'lucide-react'
import { usePipeline } from '@/store/pipelineStore'

const ROUTE_LABEL: Record<string, string> = {
  '/': 'Document Upload',
  '/weightage': 'Weightage Setting',
  '/resume-upload': 'Resume Upload',
  '/ranking': 'Candidate Ranking',
  '/dashboard': 'Recruiter Dashboard',
}

export default function Header() {
  const location = useLocation()
  const navigate = useNavigate()
  const { state } = usePipeline()
  const routeParts = location.pathname.split('/').filter(Boolean)
  const routeSection = routeParts[routeParts.length - 1]?.replace(/-/g, ' ')
  const currentLabel = ROUTE_LABEL[location.pathname] ?? (routeSection ? routeSection.replace(/\b\w/g, (letter: string) => letter.toUpperCase()) : 'Overview')

  return (
    <motion.header
      className="app-header px-6"
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      {/* ── Breadcrumb ── */}
      <div className="flex items-center gap-2 flex-1">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-1.5 text-slate-500 hover:text-sky-600 transition-colors text-[13px] font-medium"
        >
          <Home size={14} />
          <span>{state.selectedProject?.title ?? 'AI Screener'}</span>
        </button>
        <span className="text-slate-300 text-[13px]">/</span>
        <motion.span
          key={currentLabel}
          initial={{ opacity: 0, x: 6 }}
          animate={{ opacity: 1, x: 0 }}
          className="text-[13px] font-semibold text-slate-700"
        >
          {currentLabel}
        </motion.span>
      </div>

      {/* ── Right Controls ── */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-600"><span className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100"><UserRound size={15}/></span><span className="hidden sm:inline">Recruiter</span></div>
      </div>
    </motion.header>
  )
}
