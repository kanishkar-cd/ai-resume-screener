import { motion } from 'framer-motion'
import {
  FolderInput,
  Scale,
  ScanText,
  GitMerge,
  Cpu,
  ListOrdered,
  Sparkles,
  Check,
  type LucideIcon,
} from 'lucide-react'
import { AI_PIPELINE_STAGES } from '@/constants'
import { AIPipelineStageStatus } from '@/types'

const ICON_MAP: Record<string, LucideIcon> = {
  FolderInput,
  Scale,
  ScanText,
  GitMerge,
  Cpu,
  ListOrdered,
  Sparkles,
}

interface AIPipelineRailProps {
  /** 0 = not started, 1–7 = stages active/completed, 7 = all complete */
  currentAIStep: number
  isProcessing?: boolean
}

function getStatus(stageIndex: number, currentAIStep: number): AIPipelineStageStatus {
  const stageNumber = stageIndex + 1
  if (currentAIStep > stageNumber) return 'completed'
  if (currentAIStep === stageNumber) return 'active'
  return 'pending'
}

export default function AIPipelineRail({ currentAIStep, isProcessing = false }: AIPipelineRailProps) {
  return (
    <div className="card mb-5 overflow-hidden">
      {/* Header */}
      <div className="px-6 pt-4 pb-3 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Sparkles size={15} className="text-sky-500" />
          <span className="text-[12px] font-bold text-slate-700 uppercase tracking-wide">
            AI Processing Pipeline
          </span>
        </div>

        {/* Status pill */}
        {currentAIStep === 0 && (
          <span className="text-[10px] font-semibold text-slate-400 bg-slate-50 px-2.5 py-1 rounded-full border border-slate-100">
            Not started
          </span>
        )}
        {currentAIStep > 0 && currentAIStep <= AI_PIPELINE_STAGES.length && isProcessing && (
          <div className="flex items-center gap-2">
            <motion.div
              className="w-3.5 h-3.5 border-2 border-sky-500 border-t-transparent rounded-full"
              animate={{ rotate: 360 }}
              transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
            />
            <span className="text-[10px] font-semibold text-sky-600">
              Stage {currentAIStep} of {AI_PIPELINE_STAGES.length}
            </span>
          </div>
        )}
        {currentAIStep > AI_PIPELINE_STAGES.length && (
          <span className="text-[10px] font-semibold text-green-600 bg-green-50 px-2.5 py-1 rounded-full border border-green-100 flex items-center gap-1.5">
            <Check size={11} strokeWidth={2.5} />
            Complete
          </span>
        )}
      </div>

      {/* Step Rail */}
      <div className="step-rail py-5">
        {AI_PIPELINE_STAGES.map((stage, idx) => {
          const Icon = ICON_MAP[stage.icon]
          const status = getStatus(idx, currentAIStep)
          const isActive = status === 'active'
          const isDone = status === 'completed'

          return (
            <motion.div
              key={stage.id}
              className={`step-item ${isActive ? 'step-active' : isDone ? 'step-done' : ''}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.06, duration: 0.35 }}
            >
              <motion.div
                className="step-icon-wrap"
                animate={
                  isActive && isProcessing
                    ? {
                        boxShadow: [
                          '0 0 0 0 rgba(56,189,248,0.4)',
                          '0 0 0 8px rgba(56,189,248,0)',
                          '0 0 0 0 rgba(56,189,248,0)',
                        ],
                      }
                    : {}
                }
                transition={
                  isActive && isProcessing
                    ? { duration: 1.5, repeat: Infinity, ease: 'easeOut' }
                    : {}
                }
              >
                {isDone ? (
                  <Check size={14} strokeWidth={2.5} />
                ) : isActive && isProcessing ? (
                  <motion.div
                    className="w-4 h-4 border-2 border-sky-600 border-t-transparent rounded-full"
                    animate={{ rotate: 360 }}
                    transition={{ duration: 0.75, repeat: Infinity, ease: 'linear' }}
                  />
                ) : (
                  <Icon size={14} />
                )}
              </motion.div>
              <span className="step-label">{stage.shortLabel}</span>
            </motion.div>
          )
        })}
      </div>

      {/* Inline progress track */}
      {currentAIStep > 0 && (
        <div className="px-6 pb-4">
          <div className="progress-track">
            <motion.div
              className="progress-fill"
              animate={{
                width: `${Math.min((currentAIStep / AI_PIPELINE_STAGES.length) * 100, 100)}%`,
              }}
              transition={{ duration: 0.6, ease: 'easeOut' }}
            />
          </div>
          <div className="flex justify-between mt-1.5">
            <span className="text-[10px] text-slate-400">
              {isDoneAll(currentAIStep) ? 'Pipeline complete' : `Processing: ${AI_PIPELINE_STAGES[currentAIStep - 1]?.label ?? ''}`}
            </span>
            <span className="text-[11px] font-bold text-sky-600">
              {Math.min(Math.round((currentAIStep / AI_PIPELINE_STAGES.length) * 100), 100)}%
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

function isDoneAll(step: number) {
  return step > AI_PIPELINE_STAGES.length
}
