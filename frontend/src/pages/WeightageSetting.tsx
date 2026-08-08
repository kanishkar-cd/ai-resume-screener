import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Briefcase,
  Globe,
  Folder,
  GraduationCap,
  Award,
  Code2,
  Info,
  ArrowLeft,
  ArrowRight,
  type LucideIcon,
} from 'lucide-react'
import { usePipeline } from '@/store/pipelineStore'
import { useNavigate } from 'react-router-dom'
import { ROLE_PRESETS } from '@/constants'
import { WeightCriterion } from '@/types'
import { api, ApiError, type WeightDistribution } from '@/api'

const fadeUp = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0 } }
const container = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } }

const ICON_MAP: Record<string, LucideIcon> = {
  Briefcase,
  Globe,
  Folder,
  GraduationCap,
  Award,
  Code2,
}

/** Build WeightDistribution 1:1 from UI criteria (ids match backend keys). */
function toWeightDistribution(weights: WeightCriterion[]): WeightDistribution {
  const distribution: WeightDistribution = {
    skills: 0,
    experience: 0,
    projects: 0,
    education: 0,
    certifications: 0,
    languages: 0,
  }

  for (const criterion of weights) {
    distribution[criterion.id] = Math.round(criterion.weight)
  }

  return distribution
}

// ─── SVG Donut Chart Component ────────────────────────────────
function DonutChart({ weights, total }: { weights: WeightCriterion[]; total: number }) {
  const radius = 70
  const strokeWidth = 18
  const circumference = 2 * Math.PI * radius

  let accumulatedPercent = 0

  return (
    <div className="relative w-52 h-52 mx-auto flex items-center justify-center">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 180 180">
        {/* Background ring */}
        <circle
          cx="90"
          cy="90"
          r={radius}
          fill="transparent"
          stroke="#f1f5f9"
          strokeWidth={strokeWidth}
        />
        {/* Segments */}
        {weights.map((c) => {
          if (c.weight <= 0) return null
          const strokeLength = (c.weight / 100) * circumference
          const dashArray = `${strokeLength} ${circumference - strokeLength}`
          const dashOffset = -((accumulatedPercent / 100) * circumference)
          accumulatedPercent += c.weight

          return (
            <motion.circle
              key={c.id}
              cx="90"
              cy="90"
              r={radius}
              fill="transparent"
              stroke={c.color || '#3b82f6'}
              strokeWidth={strokeWidth}
              strokeDasharray={dashArray}
              strokeDashoffset={dashOffset}
              strokeLinecap="butt"
              initial={{ strokeDasharray: `0 ${circumference}` }}
              animate={{ strokeDasharray: dashArray, strokeDashoffset: dashOffset }}
              transition={{ duration: 0.5, ease: 'easeOut' }}
            />
          )
        })}
      </svg>

      {/* Center text */}
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
        <motion.span
          key={total}
          className={`text-[28px] font-extrabold leading-none ${
            Math.abs(total - 100) < 0.5 ? 'text-slate-800' : 'text-amber-600'
          }`}
          initial={{ scale: 0.85 }}
          animate={{ scale: 1 }}
        >
          {total}%
        </motion.span>
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mt-1">
          TOTAL
        </span>
      </div>
    </div>
  )
}

// ─── Main Weightage Setting Component ────────────────────────
export default function WeightageSetting() {
  const { state, dispatch, completeAndAdvance } = usePipeline()
  const navigate = useNavigate()

  const [localWeights, setLocalWeights] = useState<WeightCriterion[]>(state.weights)
  const [selectedPreset, setSelectedPreset] = useState<string>('balanced')
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(state.weightConfigSaved)

  const total = localWeights.reduce((s, w) => s + Math.round(w.weight), 0)
  const isValid = Math.abs(total - 100) < 0.5
  const canSubmit = isValid && !isSaving && Boolean(state.projectId)

  const clearSavedFlag = () => {
    setSaveSuccess(false)
    if (state.weightConfigSaved) {
      dispatch({
        type: 'SET_WEIGHT_CONFIG_SAVED',
        payload: { saved: false, weightConfigId: null },
      })
    }
  }

  const updateWeight = (id: string, requestedVal: number) => {
    setSelectedPreset('custom')
    setSaveError(null)
    clearSavedFlag()
    setLocalWeights((prev) => {
      const otherSum = prev
        .filter((w) => w.id !== id)
        .reduce((sum, w) => sum + Math.round(w.weight), 0)
      const maxAllowed = Math.max(0, 100 - otherSum)
      const clampedVal = Math.min(requestedVal, maxAllowed)

      return prev.map((w) =>
        w.id === id ? { ...w, weight: Math.max(0, clampedVal) } : w
      )
    })
  }

  const applyPreset = (presetId: string) => {
    const preset = ROLE_PRESETS.find((p) => p.id === presetId)
    if (!preset) return
    setSelectedPreset(presetId)
    setSaveError(null)
    clearSavedFlag()
    setLocalWeights((prev) =>
      prev.map((w) => {
        const newWeight = preset.weights[w.id as keyof typeof preset.weights] ?? w.weight
        return { ...w, weight: newWeight }
      })
    )
  }

  const handleContinue = async () => {
    if (!canSubmit) return

    const projectId = state.projectId
    if (!projectId) {
      setSaveError('No project found. Upload and process a job description first.')
      return
    }

    const distribution = toWeightDistribution(localWeights)
    const mappedTotal =
      distribution.skills +
      distribution.experience +
      distribution.projects +
      distribution.education +
      distribution.certifications +
      distribution.languages

    if (Math.abs(mappedTotal - 100) > 0.5) {
      setSaveError(`Weights must total 100% (currently ${mappedTotal}%).`)
      return
    }

    setIsSaving(true)
    setSaveError(null)

    try {
      localWeights.forEach((w) =>
        dispatch({ type: 'UPDATE_WEIGHT', payload: { id: w.id, weight: w.weight } })
      )

      const saved = await api.createWeightConfig(projectId, { weights: distribution })

      dispatch({
        type: 'SET_WEIGHT_CONFIG_SAVED',
        payload: { saved: true, weightConfigId: saved.id },
      })
      setSaveSuccess(true)
      completeAndAdvance()
      navigate('/resume-upload')
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to save weight configuration'
      setSaveError(message)
      dispatch({
        type: 'SET_WEIGHT_CONFIG_SAVED',
        payload: { saved: false, weightConfigId: null },
      })
    } finally {
      setIsSaving(false)
    }
  }

  const handleBack = () => {
    navigate('/')
  }

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="max-w-5xl mx-auto">
      {/* ── Main Outer Card ── */}
      <div className="card glow-border-sky p-0 overflow-hidden shadow-sm rounded-2xl bg-white">
        
        {/* ── Header Row with Presets ── */}
        <div className="p-6 border-b border-slate-100 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-[24px] font-bold text-slate-800 mb-1 tracking-tight">
              Weightage Setting
            </h1>
            <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
              Define the importance of each criterion for resume scoring. The total allocation must equal 100% before continuing to candidate ranking.
            </p>
          </div>

          {/* Role Presets */}
          <div className="flex flex-wrap items-center gap-2 flex-shrink-0">
            {ROLE_PRESETS.map((preset) => {
              const active = selectedPreset === preset.id
              return (
                <motion.button
                  key={preset.id}
                  onClick={() => applyPreset(preset.id)}
                  disabled={isSaving}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className={`px-3.5 py-1.5 rounded-lg text-[12px] font-medium transition-all duration-200 ${
                    active
                      ? 'bg-sky-50 text-sky-700 border border-sky-300 shadow-sm font-semibold'
                      : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50 hover:text-slate-800'
                  }`}
                >
                  {preset.label}
                </motion.button>
              )
            })}
          </div>
        </div>

        {/* ── Body Grid: Left Criteria Sliders | Right Donut & Legend ── */}
        <div className="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-slate-100">
          
          {/* Left Column (6 Criteria Cards) */}
          <div className="lg:col-span-7 p-6 space-y-4">
            {localWeights.map((criterion, idx) => {
              const Icon = ICON_MAP[criterion.icon || 'Briefcase'] || Briefcase

              return (
                <motion.div
                  key={criterion.id}
                  initial={{ opacity: 0, x: -12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: idx * 0.05 }}
                  className="p-4 rounded-xl border border-slate-100 bg-slate-50/40 hover:bg-white hover:border-slate-200 transition-all duration-200 group"
                >
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <div className="flex items-center gap-3">
                      {/* Icon Container */}
                      <div
                        className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 shadow-sm"
                        style={{ backgroundColor: criterion.iconBg || '#dcfce7' }}
                      >
                        <Icon size={18} style={{ color: criterion.iconColor || '#16a34a' }} />
                      </div>

                      {/* Text */}
                      <div>
                        <p className="text-[13.5px] font-bold text-slate-800 leading-tight">
                          {criterion.label}
                        </p>
                        <p className="text-[11px] text-slate-400 leading-tight mt-0.5 font-medium">
                          {criterion.description}
                        </p>
                      </div>
                    </div>

                    {/* Weight Badge */}
                    <div
                      className="px-3 py-1 rounded-lg text-[13px] font-bold flex-shrink-0"
                      style={{
                        backgroundColor: criterion.badgeBg || '#dcfce7',
                        color: criterion.badgeText || '#15803d',
                      }}
                    >
                      {criterion.weight}%
                    </div>
                  </div>

                  {/* Range Slider */}
                  <div className="relative pt-1">
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={criterion.weight}
                      disabled={isSaving}
                      onChange={(e) => updateWeight(criterion.id, Number(e.target.value))}
                      className="w-full h-2 rounded-lg appearance-none cursor-pointer outline-none bg-slate-100 disabled:opacity-60"
                      style={{
                        background: `linear-gradient(to right, ${criterion.color || '#10b981'} 0%, ${
                          criterion.color || '#10b981'
                        } ${criterion.weight}%, #e2e8f0 ${criterion.weight}%, #e2e8f0 100%)`,
                      }}
                    />
                  </div>
                </motion.div>
              )
            })}
          </div>

          {/* Right Column (Donut Chart, Legend, Info Card) */}
          <div className="lg:col-span-5 p-6 flex flex-col justify-between bg-slate-50/20">
            <div>
              {/* Donut Chart */}
              <div className="my-2">
                <DonutChart weights={localWeights} total={total} />
              </div>

              {/* Summary Legend */}
              <div className="mt-6 space-y-2.5 px-2">
                {localWeights.map((c) => (
                  <div key={c.id} className="flex items-center justify-between text-[12.5px]">
                    <div className="flex items-center gap-2.5">
                      <span
                        className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                        style={{ backgroundColor: c.color || '#3b82f6' }}
                      />
                      <span className="font-medium text-slate-700">{c.label}</span>
                    </div>
                    <span className="font-bold text-slate-600">{c.weight}%</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Info Card */}
            <div className="mt-6 rounded-2xl bg-white border border-slate-200/70 p-4 shadow-sm flex items-start gap-3">
              <div className="w-6 h-6 rounded-full bg-sky-50 text-sky-600 flex items-center justify-center flex-shrink-0 mt-0.5">
                <Info size={15} />
              </div>
              <p className="text-[11.5px] text-slate-500 leading-relaxed font-normal">
                The AI uses these weights to generate a composite score for each candidate. Heavily weighted categories have more influence on the final ranking.
              </p>
            </div>
          </div>
        </div>

        {/* ── Footer Row (Pipeline Progress + Buttons) ── */}
        <div className="p-5 bg-slate-50/60 border-t border-slate-100 flex flex-col sm:flex-row items-center justify-between gap-4">
          
          {/* Pipeline Progress Indicator */}
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">
              PIPELINE PROGRESS
            </p>
            <div className="flex items-center gap-1.5">
              <div className="w-6 h-2 rounded-full bg-sky-600" />
              <div className="w-6 h-2 rounded-full bg-sky-600" />
              <div className="w-6 h-2 rounded-full bg-slate-200" />
              <div className="w-6 h-2 rounded-full bg-slate-200" />
              <div className="w-6 h-2 rounded-full bg-slate-200" />
            </div>
            {isSaving && (
              <p className="text-[11px] text-sky-600 mt-2 font-medium">Saving weight configuration…</p>
            )}
            {saveError && (
              <p className="text-[11px] text-red-500 mt-2 max-w-sm leading-relaxed">{saveError}</p>
            )}
            {saveSuccess && !saveError && !isSaving && (
              <p className="text-[11px] text-green-600 mt-2 font-medium">Weight configuration saved.</p>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-3 w-full sm:w-auto">
            <motion.button
              onClick={handleBack}
              disabled={isSaving}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              className="btn-outline flex-1 sm:flex-initial py-2.5 px-5 text-[13px] flex items-center justify-center gap-2 font-medium"
            >
              <ArrowLeft size={15} />
              Back to Upload
            </motion.button>

            <motion.button
              onClick={handleContinue}
              disabled={!canSubmit}
              whileHover={canSubmit ? { scale: 1.02 } : undefined}
              whileTap={canSubmit ? { scale: 0.98 } : undefined}
              className={`flex-1 sm:flex-initial py-2.5 px-6 rounded-xl text-[13px] font-semibold flex items-center justify-center gap-2 transition-all shadow-sky-sm ${
                canSubmit
                  ? 'bg-sky-600 hover:bg-sky-700 text-white cursor-pointer'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed border-transparent shadow-none'
              }`}
            >
              {isSaving ? 'Saving…' : 'Continue to Resume Upload'}
              {!isSaving && <ArrowRight size={15} />}
            </motion.button>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
