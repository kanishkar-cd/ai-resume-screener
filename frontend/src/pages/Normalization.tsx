import { useState } from 'react'
import { motion } from 'framer-motion'
import { SlidersHorizontal, ArrowRight, BarChart2, TrendingUp, Zap } from 'lucide-react'
import StepIndicator from '@/components/ui/StepIndicator'
import { usePipeline } from '@/store/pipelineStore'
import { useNavigate } from 'react-router-dom'

const fadeUp = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0 } }
const container = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } }

interface NormRule {
  id: string
  label: string
  description: string
  enabled: boolean
  value?: number
}

export default function Normalization() {
  const { completeAndAdvance } = usePipeline()
  const navigate = useNavigate()

  const [rules, setRules] = useState<NormRule[]>([
    { id: 'minmax', label: 'Min-Max Scaling', description: 'Scale all scores to 0–100 range uniformly', enabled: true },
    { id: 'zscore', label: 'Z-Score Normalization', description: 'Standard deviation normalization for outlier resistance', enabled: false },
    { id: 'threshold', label: 'Minimum Score Threshold', description: 'Auto-reject candidates below minimum score', enabled: true, value: 40 },
    { id: 'tiebreak', label: 'Tie-Breaker Rule', description: 'Use experience years to resolve equal scores', enabled: true },
    { id: 'dedup', label: 'Duplicate Detection', description: 'Auto-detect and flag duplicate submissions', enabled: true },
  ])

  const toggle = (id: string) =>
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r)))

  const updateValue = (id: string, val: number) =>
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, value: val } : r)))

  const handleContinue = () => {
    completeAndAdvance()
    navigate('/scoring')
  }

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="max-w-5xl mx-auto">
      <StepIndicator />

      <motion.div variants={fadeUp} className="mb-5">
        <h1 className="text-[26px] font-bold text-slate-800 mb-1">Normalization</h1>
        <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
          Configure how extracted data is standardized and normalized before entering the scoring engine.
          These rules ensure fair and consistent candidate evaluation.
        </p>
      </motion.div>

      {/* Stats row */}
      <motion.div variants={fadeUp} className="grid grid-cols-3 gap-4 mb-5">
        {[
          { icon: BarChart2, label: 'Rules Active', value: rules.filter((r) => r.enabled).length, bg: 'bg-sky-50', color: 'text-sky-600' },
          { icon: TrendingUp, label: 'Data Quality', value: '98.4%', bg: 'bg-green-50', color: 'text-green-600' },
          { icon: Zap, label: 'Outliers Detected', value: '2', bg: 'bg-amber-50', color: 'text-amber-600' },
        ].map((stat) => {
          const Icon = stat.icon
          return (
            <div key={stat.label} className={`card p-4 ${stat.bg} border-transparent flex items-center gap-3`}>
              <div className="w-10 h-10 rounded-xl bg-white/70 flex items-center justify-center shadow-sm">
                <Icon size={18} className={stat.color} />
              </div>
              <div>
                <motion.p key={stat.value} className={`text-[20px] font-bold ${stat.color}`} initial={{ scale: 0.85 }} animate={{ scale: 1 }}>
                  {stat.value}
                </motion.p>
                <p className="text-[11px] text-slate-500">{stat.label}</p>
              </div>
            </div>
          )
        })}
      </motion.div>

      {/* Rules */}
      <motion.div variants={fadeUp} className="card p-5 mb-5">
        <div className="flex items-center gap-2 mb-4">
          <SlidersHorizontal size={16} className="text-sky-500" />
          <h2 className="text-[14px] font-semibold text-slate-700">Normalization Rules</h2>
        </div>

        <div className="space-y-3">
          {rules.map((rule, idx) => (
            <motion.div
              key={rule.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: idx * 0.06 }}
              className={`p-4 rounded-xl border transition-all ${
                rule.enabled ? 'border-sky-100 bg-sky-50/60' : 'border-slate-100 bg-slate-50'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1">
                  <p className="text-[13px] font-semibold text-slate-800">{rule.label}</p>
                  <p className="text-[11px] text-slate-400 mt-0.5">{rule.description}</p>

                  {rule.value !== undefined && rule.enabled && (
                    <div className="mt-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[11px] text-slate-500">Threshold</span>
                        <motion.span
                          key={rule.value}
                          className="text-[12px] font-bold text-sky-600"
                          initial={{ scale: 0.85 }}
                          animate={{ scale: 1 }}
                        >
                          {rule.value}%
                        </motion.span>
                      </div>
                      <input
                        type="range"
                        min={0}
                        max={80}
                        value={rule.value}
                        onChange={(e) => updateValue(rule.id, Number(e.target.value))}
                        className="w-full"
                        style={{
                          background: `linear-gradient(to right, #0284c7 0%, #0284c7 ${(rule.value / 80) * 100}%, #e2e8f0 ${(rule.value / 80) * 100}%, #e2e8f0 100%)`,
                        }}
                      />
                    </div>
                  )}
                </div>

                {/* Toggle */}
                <button
                  onClick={() => toggle(rule.id)}
                  className={`relative w-11 h-6 rounded-full transition-all duration-300 flex-shrink-0 mt-0.5 ${
                    rule.enabled ? 'bg-sky-500' : 'bg-slate-200'
                  }`}
                >
                  <motion.div
                    className="absolute top-1 w-4 h-4 bg-white rounded-full shadow-md"
                    animate={{ left: rule.enabled ? '24px' : '4px' }}
                    transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                  />
                </button>
              </div>
            </motion.div>
          ))}
        </div>
      </motion.div>

      <motion.div variants={fadeUp} className="flex justify-end">
        <motion.button
          className="btn-primary px-6"
          onClick={handleContinue}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          Continue to Scoring Engine
          <ArrowRight size={15} />
        </motion.button>
      </motion.div>
    </motion.div>
  )
}
