import { motion } from 'framer-motion'
import { useLocation, useNavigate } from 'react-router-dom'
import { BookOpen, Bell, ChevronDown, Home } from 'lucide-react'
import { PIPELINE_STAGES } from '@/constants'

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
  const currentLabel = ROUTE_LABEL[location.pathname] ?? 'AI Screener'
  const totalSteps = PIPELINE_STAGES.length

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
          <span>AI Screener</span>
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
        {/* Documentation */}
        <button className="flex items-center gap-2 text-[13px] text-slate-500 hover:text-sky-600 transition-colors font-medium px-3 py-1.5 rounded-lg hover:bg-sky-50">
          <BookOpen size={15} />
          <span className="hidden sm:inline">Documentation</span>
        </button>

        {/* Notifications */}
        <div className="relative tooltip-wrap">
          <button className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-sky-50 transition-colors text-slate-500 hover:text-sky-600">
            <Bell size={16} />
            <span className="notif-dot" />
          </button>
          <span className="tooltip">2 notifications</span>
        </div>

        {/* Divider */}
        <div className="w-px h-6 bg-slate-200" />

        {/* User Avatar */}
        <motion.button
          className="flex items-center gap-2.5 px-2 py-1.5 rounded-xl hover:bg-sky-50 transition-colors group"
          whileHover={{ scale: 1.01 }}
          whileTap={{ scale: 0.99 }}
        >
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-sky-500 to-sky-700 flex items-center justify-center text-white font-bold text-[12px] shadow-sky-sm flex-shrink-0">
            H
          </div>
          <div className="hidden sm:block text-left">
            <p className="text-[12px] font-600 text-slate-700 leading-none font-semibold">Harshini</p>
            <p className="text-[10px] text-slate-400 leading-none mt-0.5">Recruiter</p>
          </div>
          <ChevronDown size={13} className="text-slate-400 group-hover:text-sky-500 transition-colors" />
        </motion.button>
      </div>
    </motion.header>
  )
}
