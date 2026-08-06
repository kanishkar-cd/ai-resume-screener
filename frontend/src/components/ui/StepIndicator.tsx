import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import {
  Upload,
  Scale,
  FileSearch,
  SlidersHorizontal,
  Cpu,
  LayoutDashboard,
  Check,
  type LucideIcon,
} from 'lucide-react'
import { PIPELINE_STAGES } from '@/constants'
import { usePipeline } from '@/store/pipelineStore'

const ICON_MAP: Record<string, LucideIcon> = {
  Upload,
  Scale,
  FileSearch,
  SlidersHorizontal,
  Cpu,
  LayoutDashboard,
}

const ROUTE_MAP: Record<string, string> = {
  'document-upload': '/',
  'weightage-setting': '/weightage',
  'information-extraction': '/extraction',
  'normalization': '/normalization',
  'scoring-engine': '/scoring',
  'recruiter-dashboard': '/dashboard',
}

export default function StepIndicator() {
  const { state } = usePipeline()
  const navigate = useNavigate()

  return (
    <div className="card mb-5 overflow-hidden">
      {/* Step label */}
      <div className="px-6 pt-4 pb-0">
        <span className="text-[10px] font-bold text-sky-500 uppercase tracking-widest bg-sky-50 px-2.5 py-1 rounded-full border border-sky-100">
          Step {state.currentStep} of {PIPELINE_STAGES.length}
        </span>
      </div>

      {/* Step rail */}
      <div className="step-rail">
        {PIPELINE_STAGES.map((stage, idx) => {
          const Icon = ICON_MAP[stage.icon]
          const isActive = stage.step === state.currentStep
          const isDone = state.completedSteps.includes(stage.step)
          const isAccessible = stage.step <= state.currentStep
          const route = ROUTE_MAP[stage.id]

          return (
            <motion.div
              key={stage.id}
              className={`step-item ${isActive ? 'step-active' : isDone ? 'step-done' : ''}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.07, duration: 0.35 }}
              onClick={() => isAccessible && navigate(route)}
              style={{ cursor: isAccessible ? 'pointer' : 'default' }}
            >
              <motion.div
                className="step-icon-wrap"
                whileHover={isAccessible ? { scale: 1.1 } : undefined}
                whileTap={isAccessible ? { scale: 0.95 } : undefined}
              >
                {isDone && !isActive ? (
                  <Check size={15} strokeWidth={2.5} />
                ) : (
                  <Icon size={15} />
                )}
              </motion.div>
              <span className="step-label">{stage.shortLabel}</span>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}
