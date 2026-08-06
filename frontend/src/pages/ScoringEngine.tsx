import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Cpu, Play, CheckCircle2, Zap, Clock, ArrowRight, BarChart2 } from 'lucide-react'
import StepIndicator from '@/components/ui/StepIndicator'
import { usePipeline } from '@/store/pipelineStore'
import { useNavigate } from 'react-router-dom'

const fadeUp = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0 } }
const container = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } }

type RunStatus = 'idle' | 'running' | 'done'

interface ScoringStep {
  id: string
  label: string
  detail: string
  duration: number
}

const SCORING_STEPS: ScoringStep[] = [
  { id: 'load', label: 'Loading candidate data', detail: '4 profiles queued', duration: 600 },
  { id: 'vectorize', label: 'Vectorizing JD & resumes', detail: 'Semantic embedding via transformer model', duration: 1000 },
  { id: 'match', label: 'Matching skills & experience', detail: 'Cross-referencing 42 criteria', duration: 900 },
  { id: 'weight', label: 'Applying weightage matrix', detail: 'Using your custom weights', duration: 700 },
  { id: 'rank', label: 'Computing final scores & ranks', detail: 'Normalization complete', duration: 800 },
]

export default function ScoringEngine() {
  const { dispatch, completeAndAdvance, state } = usePipeline()
  const navigate = useNavigate()
  const [runStatus, setRunStatus] = useState<RunStatus>('idle')
  const [stepsDone, setStepsDone] = useState<string[]>([])
  const [currentStep, setCurrentStep] = useState<string | null>(null)

  const runScoring = async () => {
    setRunStatus('running')
    setStepsDone([])

    for (const step of SCORING_STEPS) {
      setCurrentStep(step.id)
      await new Promise((r) => setTimeout(r, step.duration))
      setStepsDone((prev) => [...prev, step.id])
    }

    setCurrentStep(null)
    dispatch({ type: 'RUN_SCORING' })
    setRunStatus('done')
  }

  const handleContinue = () => {
    completeAndAdvance()
    navigate('/dashboard')
  }

  const progressPct = Math.round((stepsDone.length / SCORING_STEPS.length) * 100)

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="max-w-5xl mx-auto">
      <StepIndicator />

      <motion.div variants={fadeUp} className="mb-5">
        <h1 className="text-[26px] font-bold text-slate-800 mb-1">Scoring Engine</h1>
        <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
          The AI scoring pipeline evaluates each candidate against the job description using your
          configured weightage matrix and normalization rules.
        </p>
      </motion.div>

      {/* Config Summary */}
      <motion.div variants={fadeUp} className="grid grid-cols-3 gap-4 mb-5">
        {[
          { icon: BarChart2, label: 'Criteria', value: state.weights.length, color: 'text-sky-600', bg: 'bg-sky-50' },
          { icon: Zap, label: 'Candidates', value: 4, color: 'text-sky-600', bg: 'bg-sky-50' },
          { icon: Clock, label: 'Est. Time', value: '~8s', color: 'text-slate-600', bg: 'bg-slate-50' },
        ].map((s) => {
          const Icon = s.icon
          return (
            <div key={s.label} className={`card p-4 ${s.bg} border-transparent flex items-center gap-3`}>
              <div className="w-10 h-10 rounded-xl bg-white/70 flex items-center justify-center shadow-sm">
                <Icon size={18} className={s.color} />
              </div>
              <div>
                <p className={`text-[22px] font-bold ${s.color}`}>{s.value}</p>
                <p className="text-[11px] text-slate-500">{s.label}</p>
              </div>
            </div>
          )
        })}
      </motion.div>

      {/* Pipeline Steps */}
      <motion.div variants={fadeUp} className="card p-5 mb-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Cpu size={16} className="text-sky-500" />
            <h2 className="text-[14px] font-semibold text-slate-700">Scoring Pipeline</h2>
          </div>

          {runStatus === 'idle' && (
            <motion.button
              className="btn-primary py-2 px-5 text-[12px]"
              onClick={runScoring}
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.97 }}
            >
              <Play size={13} />
              Run Scoring
            </motion.button>
          )}

          {runStatus === 'running' && (
            <div className="flex items-center gap-2 text-[12px] text-sky-600 font-medium">
              <motion.div
                className="w-4 h-4 border-2 border-sky-500 border-t-transparent rounded-full"
                animate={{ rotate: 360 }}
                transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
              />
              Processing... {progressPct}%
            </div>
          )}

          {runStatus === 'done' && (
            <div className="flex items-center gap-1.5 text-[12px] text-green-600 font-semibold">
              <CheckCircle2 size={14} />
              Scoring complete
            </div>
          )}
        </div>

        {/* Progress bar */}
        {runStatus !== 'idle' && (
          <div className="progress-track mb-4">
            <motion.div
              className="progress-fill"
              animate={{ width: `${progressPct}%` }}
              transition={{ duration: 0.4 }}
            />
          </div>
        )}

        {/* Steps */}
        <div className="space-y-2">
          {SCORING_STEPS.map((step, idx) => {
            const isDone = stepsDone.includes(step.id)
            const isRunning = currentStep === step.id

            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: idx * 0.06 }}
                className={`flex items-center gap-3 p-3.5 rounded-xl border transition-all ${
                  isDone
                    ? 'border-green-100 bg-green-50'
                    : isRunning
                    ? 'border-sky-200 bg-sky-50'
                    : 'border-slate-100 bg-slate-50'
                }`}
              >
                <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0">
                  {isDone ? (
                    <CheckCircle2 size={18} className="text-green-500" />
                  ) : isRunning ? (
                    <motion.div
                      className="w-4 h-4 border-2 border-sky-500 border-t-transparent rounded-full"
                      animate={{ rotate: 360 }}
                      transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
                    />
                  ) : (
                    <div className="w-4 h-4 rounded-full border-2 border-slate-200" />
                  )}
                </div>
                <div className="flex-1">
                  <p className={`text-[13px] font-semibold ${isDone ? 'text-green-700' : isRunning ? 'text-sky-700' : 'text-slate-400'}`}>
                    {step.label}
                  </p>
                  <p className="text-[11px] text-slate-400">{step.detail}</p>
                </div>
                <span className="text-[10px] text-slate-300 font-mono">{step.duration}ms</span>
              </motion.div>
            )
          })}
        </div>
      </motion.div>

      <motion.div variants={fadeUp} className="flex justify-end">
        <motion.button
          className="btn-primary px-6"
          onClick={handleContinue}
          disabled={runStatus !== 'done'}
          whileHover={runStatus === 'done' ? { scale: 1.02 } : undefined}
          whileTap={runStatus === 'done' ? { scale: 0.98 } : undefined}
        >
          View Recruiter Dashboard
          <ArrowRight size={15} />
        </motion.button>
      </motion.div>
    </motion.div>
  )
}
