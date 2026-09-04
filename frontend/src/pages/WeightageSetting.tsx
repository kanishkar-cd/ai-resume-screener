import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, Award, Briefcase, Check, ChevronDown, Code2, Folder, Globe, GraduationCap, type LucideIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type NormalizedJobDescription, type WeightDistribution } from '@/api'
import { ROLE_PRESETS } from '@/constants'
import { usePipeline } from '@/store/pipelineStore'
import type { WeightCriterion } from '@/types'

const ICON_MAP: Record<string, LucideIcon> = { Briefcase, Globe, Folder, GraduationCap, Award, Code2 }

function toDistribution(weights: WeightCriterion[]): WeightDistribution {
  return weights.reduce<WeightDistribution>((result, criterion) => {
    result[criterion.id as keyof WeightDistribution] = Math.round(criterion.weight)
    return result
  }, { required_skills: 45, responsibilities: 40, preferred_skills: 15 })
}

const splitValues = (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean)

function Chips({ items }: { items: string[] }) {
  if (!items.length) return <span className="text-[12px] text-slate-400">Not configured</span>
  return <div className="flex flex-wrap gap-1.5">{items.map((item) => <span key={item} className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-[10px] font-medium text-slate-600">{item}</span>)}</div>
}

export default function WeightageSetting() {
  const { state, dispatch, completeAndAdvance } = usePipeline()
  const navigate = useNavigate()
  const localWeights = state.weights
  const [selectedPreset, setSelectedPreset] = useState('balanced')
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(state.weightConfigSaved)
  const [jobProfile, setJobProfile] = useState<NormalizedJobDescription | null>(null)
  const [advanced, setAdvanced] = useState({ passingScore: 60, minExperience: 0, requiredDegree: '', mandatorySkills: '', preferredSkills: '', knockoutRules: '', customKeywords: '' })

  const total = localWeights.reduce((sum, criterion) => sum + Math.round(criterion.weight), 0)
  const weightsValid = localWeights.every((criterion) => criterion.weight >= 0 && criterion.weight <= 100)
  const rulesValid = advanced.passingScore >= 0 && advanced.passingScore <= 100 && advanced.minExperience >= 0
  const isValid = total === 100 && weightsValid && rulesValid
  const canSubmit = isValid && !isSaving && Boolean(state.projectId)

  useEffect(() => {
    let active = true
    if (!state.projectId) return
    api.getWeightConfig(state.projectId).then((config) => {
      if (!active || !config?.weights) return
      Object.entries(config.weights).forEach(([id, weight]) => dispatch({ type: 'UPDATE_WEIGHT', payload: { id, weight } }))
      dispatch({ type: 'SET_WEIGHT_CONFIG_SAVED', payload: { saved: true, weightConfigId: config.id } })
      setAdvanced({ passingScore: config.passing_score, minExperience: config.min_experience_years, requiredDegree: config.required_degree ?? '', mandatorySkills: config.mandatory_skills.join(', '), preferredSkills: config.preferred_skills.join(', '), knockoutRules: config.knockout_rules.map((rule) => rule.rule_type).join(', '), customKeywords: config.custom_keywords.join(', ') })
      const matchingPreset = ROLE_PRESETS.find((preset) => Object.entries(preset.weights).every(([key, value]) => config.weights[key as keyof WeightDistribution] === value))
      setSelectedPreset(matchingPreset?.id ?? 'custom')
      setSaveSuccess(true)
    }).catch(() => undefined)
    return () => { active = false }
  }, [dispatch, state.projectId])

  useEffect(() => {
    if (!state.jdDocumentId) return
    let active = true
    api.getNormalizedDocument(state.jdDocumentId).then((document) => {
      if (active && 'required_skills' in document) setJobProfile(document)
    }).catch(() => undefined)
    return () => { active = false }
  }, [state.jdDocumentId])

  const markDirty = () => {
    setSaveError(null)
    setSaveSuccess(false)
    if (state.weightConfigSaved) dispatch({ type: 'SET_WEIGHT_CONFIG_SAVED', payload: { saved: false, weightConfigId: null } })
  }

  const updateWeight = (id: string, requested: number) => {
    const value = Number.isFinite(requested) ? Math.min(100, Math.max(0, requested)) : 0
    setSelectedPreset('custom')
    markDirty()
    dispatch({ type: 'UPDATE_WEIGHT', payload: { id, weight: value } })
  }

  const updateAdvanced = <K extends keyof typeof advanced>(key: K, value: (typeof advanced)[K]) => {
    markDirty()
    setAdvanced((current) => ({ ...current, [key]: value }))
  }

  const applyPreset = (presetId: string) => {
    const preset = ROLE_PRESETS.find((item) => item.id === presetId)
    if (!preset) return
    markDirty()
    setSelectedPreset(presetId)
    localWeights.forEach((criterion) => dispatch({ type: 'UPDATE_WEIGHT', payload: { id: criterion.id, weight: preset.weights[criterion.id] ?? criterion.weight } }))
  }

  const saveConfiguration = async (continueAfterSave = false) => {
    if (!canSubmit || !state.projectId) return false
    setIsSaving(true)
    setSaveError(null)
    try {
      const distribution = toDistribution(localWeights)
      const saved = await api.createWeightConfig(state.projectId, {
        weights: distribution,
        passing_score: advanced.passingScore,
        min_experience_years: advanced.minExperience,
        required_degree: advanced.requiredDegree.trim() || null,
        mandatory_skills: splitValues(advanced.mandatorySkills),
        preferred_skills: splitValues(advanced.preferredSkills),
        knockout_rules: splitValues(advanced.knockoutRules).map((rule_type) => ({ rule_type, enabled: true })),
        custom_keywords: splitValues(advanced.customKeywords),
      })
      localWeights.forEach((criterion) => dispatch({ type: 'UPDATE_WEIGHT', payload: { id: criterion.id, weight: criterion.weight } }))
      dispatch({ type: 'SET_WEIGHT_CONFIG_SAVED', payload: { saved: true, weightConfigId: saved.id } })
      setSaveSuccess(true)
      if (continueAfterSave) {
        completeAndAdvance()
        navigate(`/projects/${state.projectId}/resumes`)
      }
      return true
    } catch (error) {
      setSaveError(error instanceof ApiError ? error.message : error instanceof Error ? error.message : 'Failed to save weight configuration')
      return false
    } finally {
      setIsSaving(false)
    }
  }

  const experienceLabel = jobProfile?.experience_requirements
    .slice()
    .sort((a, b) => a.display_value.length - b.display_value.length)[0]?.display_value
  const ruleValues = (key: 'mandatorySkills' | 'preferredSkills' | 'customKeywords' | 'knockoutRules') => {
    const configured = splitValues(advanced[key])
    if (configured.length) return configured
    if (key === 'mandatorySkills') return jobProfile?.required_skills ?? []
    if (key === 'preferredSkills') return jobProfile?.preferred_skills ?? []
    return []
  }
  const continueToResumes = () => {
    if (!canSubmit || !state.projectId) return
    if (saveSuccess) {
      completeAndAdvance()
      navigate(`/projects/${state.projectId}/resumes`)
      return
    }
    void saveConfiguration(true)
  }

  return <div className="mx-auto max-w-6xl pb-28">
    <header className="mb-8">
      <h1 className="text-[28px] font-bold tracking-tight text-slate-900">Scoring Configuration</h1>
      <p className="mt-2 text-[13px] text-slate-500">Define how candidates will be evaluated for this position.</p>
      {jobProfile && <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-slate-200 bg-white px-5 py-4">
        <div className="mr-auto"><p className="text-[14px] font-semibold text-slate-900">{jobProfile.job_title || 'Job profile'}</p><p className="mt-0.5 text-[11px] text-slate-500">{jobProfile.domain || 'Domain not specified'}</p></div>
        <span className="text-[11px] text-slate-500"><strong className="text-slate-800">{jobProfile.required_skills.length}</strong> required skills</span>
        <span className="text-[11px] text-slate-500"><strong className="text-slate-800">{jobProfile.preferred_skills.length}</strong> preferred skills</span>
        {experienceLabel && <span className="text-[11px] text-slate-500">Experience: <strong className="text-slate-800">{experienceLabel}</strong></span>}
      </div>}
    </header>

    <section className="rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-col gap-4 border-b border-slate-100 px-6 py-5 md:flex-row md:items-center md:justify-between">
        <div><h2 className="text-[16px] font-semibold text-slate-900">Weight Allocation</h2><p className="mt-1 text-[11px] text-slate-500">Allocate exactly 100% across the six scoring criteria.</p></div>
        <div className="inline-flex w-fit rounded-lg border border-slate-200 bg-slate-50 p-1">{ROLE_PRESETS.map((preset) => <button key={preset.id} type="button" disabled={isSaving} onClick={() => applyPreset(preset.id)} className={`rounded-md px-3 py-1.5 text-[11px] font-medium transition-colors ${selectedPreset === preset.id ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}>{preset.label}</button>)}</div>
      </div>

      <div className="divide-y divide-slate-100 px-6">
        {localWeights.map((criterion) => {
          const Icon = ICON_MAP[criterion.icon || 'Briefcase'] || Briefcase
          return <div key={criterion.id} className="grid gap-4 py-5 md:grid-cols-[minmax(220px,1fr)_minmax(300px,1.4fr)] md:items-center">
            <div className="flex items-start gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600"><Icon size={17}/></span><div><p className="text-[13px] font-semibold text-slate-800">{criterion.label}</p><p className="mt-1 text-[11px] leading-relaxed text-slate-500">{criterion.description}</p></div></div>
            <div className="flex items-center gap-4"><input aria-label={`${criterion.label} weight`} type="range" min={0} max={100} value={criterion.weight} disabled={isSaving} onChange={(event) => updateWeight(criterion.id, Number(event.target.value))} className="h-1.5 min-w-0 flex-1 cursor-pointer accent-blue-600 disabled:cursor-not-allowed disabled:opacity-50"/><label className="flex items-center rounded-lg border border-slate-200 bg-white focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100"><input aria-label={`${criterion.label} percentage`} type="number" min={0} max={100} value={criterion.weight} disabled={isSaving} onChange={(event) => updateWeight(criterion.id, Number(event.target.value))} className="w-14 border-0 bg-transparent px-2 py-1.5 text-right text-[12px] font-semibold text-slate-800 outline-none"/><span className="pr-2 text-[11px] text-slate-400">%</span></label></div>
          </div>
        })}
      </div>

      <div className={`flex items-center justify-between border-t px-6 py-5 ${isValid ? 'border-emerald-100 bg-emerald-50/40' : total > 100 ? 'border-red-100 bg-red-50/40' : 'border-slate-100 bg-slate-50/60'}`}>
        <div><p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Total allocation</p><p className={`mt-1 text-[30px] font-bold tracking-tight ${isValid ? 'text-emerald-700' : total > 100 ? 'text-red-600' : 'text-slate-900'}`}>{total}%</p></div>
        <p className={`flex items-center gap-1.5 text-[12px] font-medium ${isValid ? 'text-emerald-700' : total > 100 ? 'text-red-600' : 'text-slate-500'}`}>{isValid ? <><Check size={14}/> Ready to continue</> : total > 100 ? `${total - 100}% over allocation` : `${100 - total}% remaining`}</p>
      </div>
    </section>

    <details className="group mt-6 rounded-xl border border-slate-200 bg-white">
      <summary className="flex cursor-pointer list-none items-center justify-between px-6 py-5"><div><h2 className="text-[15px] font-semibold text-slate-900">Screening Rules</h2><p className="mt-1 text-[11px] text-slate-500">Define mandatory requirements and knockout conditions.</p></div><ChevronDown size={16} className="text-slate-400 transition-transform group-open:rotate-180"/></summary>
      <div className="grid gap-5 border-t border-slate-100 px-6 py-6 md:grid-cols-2">
        <label className="text-[11px] font-semibold text-slate-600">Passing score<input type="number" min={0} max={100} value={advanced.passingScore} onChange={(event) => updateAdvanced('passingScore', Number(event.target.value))} className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-[12px] outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"/></label>
        <label className="text-[11px] font-semibold text-slate-600">Minimum experience (years)<input type="number" min={0} value={advanced.minExperience} onChange={(event) => updateAdvanced('minExperience', Number(event.target.value))} className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-[12px] outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"/></label>
        <label className="text-[11px] font-semibold text-slate-600">Required degree<input value={advanced.requiredDegree} onChange={(event) => updateAdvanced('requiredDegree', event.target.value)} placeholder={jobProfile?.degree_requirements[0] ?? ''} className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-[12px] outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"/></label>
        {([['Mandatory skills','mandatorySkills'],['Preferred skills','preferredSkills'],['Custom keywords','customKeywords'],['Knockout rules','knockoutRules']] as const).map(([label, key]) => <label key={key} className="text-[11px] font-semibold text-slate-600">{label}<input value={advanced[key]} onChange={(event) => updateAdvanced(key, event.target.value)} placeholder="Comma separated" className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-[12px] outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"/><div className="mt-2"><Chips items={ruleValues(key)}/></div></label>)}
      </div>
    </details>

    {(saveError || saveSuccess) && <div className={`mt-5 rounded-lg border px-4 py-3 text-[12px] ${saveError ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{saveError || 'Weight configuration saved.'}</div>}

    <div className="sticky bottom-0 z-10 mt-8 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white/95 px-5 py-4 shadow-sm backdrop-blur sm:flex-row sm:items-center sm:justify-between">
      <button type="button" onClick={() => navigate(`/projects/${state.projectId}/job-description`)} disabled={isSaving} className="btn-outline justify-center"><ArrowLeft size={14}/> Back to Job Description</button>
      <div className="flex flex-col gap-2 sm:flex-row"><button type="button" onClick={() => void saveConfiguration(false)} disabled={!canSubmit || saveSuccess} className="btn-outline justify-center disabled:cursor-not-allowed disabled:opacity-50">{isSaving ? 'Saving…' : saveSuccess ? 'Configuration Saved' : 'Save Configuration'}</button><button type="button" onClick={continueToResumes} disabled={!canSubmit} className="btn-primary justify-center disabled:cursor-not-allowed disabled:opacity-50">Continue to Resume Upload <ArrowRight size={14}/></button></div>
    </div>
  </div>
}
