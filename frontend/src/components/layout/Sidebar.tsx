import { useEffect } from 'react'
import { motion } from 'framer-motion'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Upload,
  Scale,
  FolderUp,
  ListOrdered,
  LayoutDashboard,
  CheckCircle2,
  Shield,
  type LucideIcon,
} from 'lucide-react'
import { usePipeline } from '@/store/pipelineStore'
import { NAV_STAGES } from '@/constants'

const ICON_MAP: Record<string, LucideIcon> = {
  Upload,
  Scale,
  FolderUp,
  ListOrdered,
  LayoutDashboard,
}

const ROUTE_TO_STEP: Record<string, number> = {
  '/': 1,
  '/weightage': 2,
  '/resume-upload': 3,
  '/ranking': 4,
  '/dashboard': 5,
}

export default function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { state, goToStep } = usePipeline()

  // Always determine active step from current URL pathname
  const activeStepFromUrl = ROUTE_TO_STEP[location.pathname] ?? state.currentStep
  const currentStep = activeStepFromUrl
  const totalNavSteps = NAV_STAGES.length

  // Keep store in sync with URL
  useEffect(() => {
    if (activeStepFromUrl !== state.currentStep) {
      goToStep(activeStepFromUrl)
    }
  }, [location.pathname, activeStepFromUrl])

  const progressPercent = Math.round(
    ((currentStep - 1) / (totalNavSteps - 1)) * 100
  )

  return (
    <motion.aside
      className="app-sidebar glow-border-sky"
      initial={{ x: -40, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.4, ease: 'easeOut' }}
    >
      {/* ── Logo Header ── */}
      <div className="px-5 pt-5 pb-3 border-b border-sky-100/60 bg-white/60">
        <motion.div
          className="flex items-center gap-3"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.15 }}
        >
          <div className="w-9 h-9 rounded-xl overflow-hidden flex items-center justify-center bg-gradient-to-br from-sky-400 to-sky-600 shadow-sky-sm flex-shrink-0 glow-border-sky-sm">
            <img
              src="/images/logo.png"
              alt="AI Screener Logo"
              className="w-full h-full object-cover"
              onError={(e) => {
                const t = e.currentTarget
                t.style.display = 'none'
                const parent = t.parentElement
                if (parent) parent.innerHTML = '<span style="color:white;font-weight:800;font-size:15px">AI</span>'
              }}
            />
          </div>
          <div>
            <p className="text-[13.5px] font-bold text-slate-800 leading-tight tracking-tight">
              AI Screener
            </p>
            <p className="text-[10px] text-sky-600 leading-tight font-semibold mt-0.5">
              Enterprise Resume Pipeline
            </p>
          </div>
        </motion.div>
      </div>

      {/* ── Workflow Stages Section ── */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden py-4">
        <p className="px-5 mb-3 text-[10px] font-extrabold text-sky-600 uppercase tracking-widest">
          Workflow Stages
        </p>

        {/* 5 Stage Headings */}
        <div className="space-y-2 px-3">
          {NAV_STAGES.map((stage, idx) => {
            const Icon = ICON_MAP[stage.icon]
            const route = stage.route
            const active = stage.step === currentStep
            const completed = state.completedSteps.includes(stage.step) || stage.step < currentStep

            return (
              <motion.div
                key={stage.id}
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.06 + idx * 0.05, duration: 0.3 }}
              >
                <motion.button
                  onClick={() => {
                    goToStep(stage.step)
                    navigate(route)
                  }}
                  className={`w-full text-left p-2.5 rounded-xl flex items-center justify-between transition-all duration-200 cursor-pointer ${
                    active
                      ? 'bg-gradient-to-r from-sky-600 to-sky-500 text-white shadow-lg glow-border-sky-sm font-bold scale-[1.02]'
                      : completed
                      ? 'bg-sky-50/90 text-sky-800 border border-sky-200/80 hover:bg-sky-100/80'
                      : 'bg-white/80 text-slate-600 border border-slate-100 hover:bg-slate-50'
                  }`}
                  whileHover={{ x: 4 }}
                  whileTap={{ scale: 0.98 }}
                >
                  {/* Node Circle & Title */}
                  <div className="flex items-center gap-2.5 min-w-0">
                    {/* Node Circle */}
                    <div
                      className={`w-7 h-7 rounded-full flex items-center justify-center font-extrabold text-[11px] flex-shrink-0 ${
                        active
                          ? 'bg-white text-sky-600 shadow-md'
                          : completed
                          ? 'bg-sky-500 text-white'
                          : 'bg-slate-100 text-slate-500 border border-slate-200'
                      }`}
                    >
                      {completed && !active ? (
                        <CheckCircle2 size={15} className="text-white" />
                      ) : (
                        stage.step
                      )}
                    </div>

                    {/* Heading Icon & Label */}
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <Icon size={14} className={active ? 'text-white' : completed ? 'text-sky-600' : 'text-slate-400'} />
                        <p className={`text-[12px] truncate leading-tight ${active ? 'font-bold text-white' : 'font-semibold text-slate-700'}`}>
                          {stage.label}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Step Tag */}
                  <span
                    className={`text-[10px] font-extrabold px-1.5 py-0.5 rounded flex-shrink-0 ${
                      active
                        ? 'bg-white/20 text-white'
                        : completed
                        ? 'bg-sky-100 text-sky-700'
                        : 'bg-slate-100 text-slate-400'
                    }`}
                  >
                    0{stage.step}
                  </span>
                </motion.button>
              </motion.div>
            )
          })}
        </div>
      </div>

      {/* ── Pipeline Progress Card ── */}
      <div className="p-3.5 mx-3 mb-3 rounded-xl bg-gradient-to-br from-sky-50 to-blue-50/60 border border-sky-200/80 glow-border-sky-sm">
        <div className="flex items-center justify-between mb-1.5">
          <p className="text-[10px] font-bold text-sky-700 uppercase tracking-widest">
            Pipeline Progress
          </p>
          <span className="text-[11px] font-extrabold text-sky-700">
            {progressPercent}%
          </span>
        </div>
        <div className="progress-track">
          <motion.div
            className="progress-fill"
            initial={{ width: 0 }}
            animate={{ width: `${progressPercent}%` }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
          />
        </div>
      </div>

      {/* ── Footer ── */}
      <div className="px-4 py-2.5 border-t border-slate-100">
        <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
          <Shield size={11} className="text-sky-500" />
          <span>© 2026 AI Screener. Enterprise Edition</span>
        </div>
      </div>
    </motion.aside>
  )
}
