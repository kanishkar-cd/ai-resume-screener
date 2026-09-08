import React, { useCallback, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Search,
  Filter,
  X,
  Sparkles,
  CheckCircle2,
  TrendingUp,
  AlertCircle,
  Users,
  Trophy,
  Star,
  Briefcase,
  Mail,
  ChevronRight,
  UserCheck,
  ThumbsDown,
  HelpCircle,
  Download,
  ArrowRight,
  Award,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import { usePipeline } from '@/store/pipelineStore'
import { Candidate, ScreeningStatus } from '@/types'
import {
  api,
  type CandidateInsights,
  type CandidateRanking as ApiCandidateRanking,
  type CandidateScore as ApiCandidateScore,
  type WeightConfig,
  type ExtractedResume,
  type NormalizedResume,
  type NormalizedJobDescription,
  type Document as ApiDocument,
} from '@/api'
import type { MatchVerdict } from '@/types'
import { CandidateProfile } from '@/components/ui/DocumentProfiles'

// ─── Animation variants ───────────────────────────────────────────────────────
const fadeUp = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0 } }
const container = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } }

// ─── Recommendation helpers ───────────────────────────────────────────────────
function getRecommendationConfig(candidate: Candidate): {
  label: string
  shortLabel: string
  cls: string
  iconColor: string
  Icon: typeof CheckCircle2
} {
  if (candidate.isKnockedOut || candidate.recommendation === 'REJECT' || candidate.overallScore < 40) {
    return {
      label: 'Not Relevant',
      shortLabel: 'Reject',
      cls: 'bg-red-50 text-red-700 border border-red-200',
      iconColor: 'text-red-400',
      Icon: ThumbsDown,
    }
  }
  if (candidate.overallScore >= 60 && (candidate.recommendation === 'SHORTLIST' || candidate.overallScore >= 70)) {
    return {
      label: 'Strong Match',
      shortLabel: 'Shortlist',
      cls: 'bg-emerald-50 text-emerald-700 border border-emerald-200',
      iconColor: 'text-emerald-500',
      Icon: CheckCircle2,
    }
  }
  return {
    label: 'Relevant',
    shortLabel: 'Consider',
    cls: 'bg-amber-50 text-amber-700 border border-amber-200',
    iconColor: 'text-amber-500',
    Icon: HelpCircle,
  }
}

function getScoreColor(score: number) {
  if (score >= 60) return 'text-emerald-600'
  if (score >= 35) return 'text-amber-500'
  return 'text-red-500'
}

function getScoreBg(score: number) {
  if (score >= 60) return 'bg-emerald-50 border-emerald-200'
  if (score >= 35) return 'bg-amber-50 border-amber-200'
  return 'bg-red-50 border-red-200'
}

function recommendationToStatus(recommendation: string, knockedOut: boolean, score?: number): ScreeningStatus {
  if (knockedOut || recommendation === 'REJECT' || (score !== undefined && score < 40)) return 'rejected'
  if (score !== undefined && score < 60) return 'pending'
  return 'screened'
}

// ─── Score Breakdown helpers (kept for drawer) ────────────────────────────────
function getScoreClass(score: number) {
  if (score >= 80) return 'score-high'
  if (score >= 60) return 'score-med'
  return 'score-low'
}

// ─── Requirement verdicts & evidence (for drawer) ─────────────────────────────
type EvidenceDisplay = { label: string; source: string; snippet: string }

function truncateEvidence(text: string, max = 180) {
  const compact = text.replace(/\s+/g, ' ').trim()
  return compact.length > max ? `${compact.slice(0, max - 1)}...` : compact
}

function addRequirementLabels(map: Map<string, string>, prefix: string, values: Array<string | null | undefined>) {
  values.filter(Boolean).forEach((value, index) => { map.set(`${prefix}:${index + 1}`, value as string) })
}

function buildRequirementLabelMap(jd: NormalizedJobDescription | null) {
  const map = new Map<string, string>()
  if (!jd) return map
  addRequirementLabels(map, 'skill', jd.skills)
  addRequirementLabels(map, 'degree', jd.degree_requirements)
  addRequirementLabels(map, 'responsibility', jd.responsibilities)
  addRequirementLabels(map, 'certification', jd.certifications)
  addRequirementLabels(map, 'experience', jd.experience_requirements.map((req) => req.display_value))
  return map
}

function buildEvidenceMap(profile: { normalized: NormalizedResume; extracted: ExtractedResume | null; document: ApiDocument } | null) {
  const map = new Map<string, EvidenceDisplay>()
  const extracted = profile?.extracted
  if (!extracted) return map
  extracted.experience.forEach((item, index) => {
    const title = item.title || item.designation || 'Work experience'
    const source = [title, item.company].filter(Boolean).join(' at ')
    const text = [item.description, ...(item.responsibilities || [])].filter(Boolean).join(' ')
    map.set(`experience:${index + 1}`, { label: source, source: 'Work experience', snippet: truncateEvidence(text || item.duration || source) })
  })
  extracted.projects.forEach((item, index) => {
    const technologies = item.technologies?.length ? ` Technologies: ${item.technologies.join(', ')}.` : ''
    const text = `${item.description || ''}${technologies}`.trim()
    map.set(`project:${index + 1}`, { label: item.name || `Project ${index + 1}`, source: 'Project', snippet: truncateEvidence(text || item.name || `Project ${index + 1}`) })
  })
  return map
}

function verdictStatusClass(status: MatchVerdict['status']) {
  if (status === 'MATCHED') return 'border-green-200 bg-green-50 text-green-700'
  if (status === 'NO_MATCH') return 'border-red-200 bg-red-50 text-red-700'
  return 'border-amber-200 bg-amber-50 text-amber-700'
}

function verdictStatusLabel(status: MatchVerdict['status']) {
  if (status === 'MATCHED') return 'Matched'
  if (status === 'NO_MATCH') return 'Not Matched'
  return 'Unclear'
}

// ─── Explanation Drawer ───────────────────────────────────────────────────────
interface ExplanationDrawerProps {
  candidate: Candidate | null
  projectId: string | null
  jdDocumentId: string | null
  assessmentCandidates?: import('@/types').AssessmentCandidate[]
  onClose: () => void
}

function ExplanationDrawer({ candidate, projectId, jdDocumentId, assessmentCandidates, onClose }: ExplanationDrawerProps) {
  const [insights, setInsights] = useState<CandidateInsights | null>(null)
  const [loadingInsights, setLoadingInsights] = useState(false)
  const [resumeProfile, setResumeProfile] = useState<{ normalized: NormalizedResume; extracted: ExtractedResume | null; document: ApiDocument } | null>(null)
  const [profileError, setProfileError] = useState<string | null>(null)
  const [loadingProfile, setLoadingProfile] = useState(false)
  const [normalizedJd, setNormalizedJd] = useState<NormalizedJobDescription | null>(null)
  const [jdError, setJdError] = useState<string | null>(null)
  const [loadingJd, setLoadingJd] = useState(false)

  React.useEffect(() => {
    if (!candidate?.id) { setInsights(null); setLoadingInsights(false); return }
    let isMounted = true
    setLoadingInsights(true)
    api.getInsights(candidate.id)
      .then((res) => { if (isMounted) setInsights(res) })
      .catch(() => { if (isMounted) setInsights(null) })
      .finally(() => { if (isMounted) setLoadingInsights(false) })
    return () => { isMounted = false }
  }, [candidate?.id])

  React.useEffect(() => {
    if (!candidate?.id) { setResumeProfile(null); setProfileError(null); return }
    let active = true
    setLoadingProfile(true)
    Promise.all([api.getNormalizedDocument(candidate.id), api.getExtractedDocument(candidate.id).catch(() => null), api.getDocument(candidate.id)])
      .then(([normalized, extracted, document]) => {
        if (!active) return
        if (!('job_titles' in normalized)) throw new Error('Normalized resume data was not returned.')
        setResumeProfile({ normalized, extracted: extracted && 'candidate_name' in extracted ? extracted : null, document })
        setProfileError(null)
      })
      .catch((err) => { if (active) setProfileError(err instanceof Error ? err.message : 'Unable to load resume data.') })
      .finally(() => { if (active) setLoadingProfile(false) })
    return () => { active = false }
  }, [candidate?.id])

  React.useEffect(() => {
    if (!candidate || (!jdDocumentId && !projectId)) { setNormalizedJd(null); setJdError(null); return }
    let active = true
    setLoadingJd(true)
    const jdRequest = jdDocumentId ? Promise.resolve({ id: jdDocumentId }) : api.getJobDescription(projectId!)
    jdRequest
      .then((document) => api.getNormalizedDocument(document.id))
      .then((normalized) => {
        if (!active) return
        if (!('job_title' in normalized)) throw new Error('Normalized job description data was not returned.')
        setNormalizedJd(normalized)
        setJdError(null)
      })
      .catch((err) => { if (!active) return; setNormalizedJd(null); setJdError(err instanceof Error ? err.message : 'Unable to load job description.') })
      .finally(() => { if (active) setLoadingJd(false) })
    return () => { active = false }
  }, [candidate, jdDocumentId, projectId])

  const aiSummaryText = insights?.summary || candidate?.aiExplanation || 'AI screening explanation will appear here once the screening pipeline has processed this candidate.'
  const displayStrengths = insights?.strengths?.length ? insights.strengths : candidate?.keyStrengths || []
  const displayWeaknesses = insights?.weaknesses?.length ? insights.weaknesses : candidate?.keyWeaknesses || []
  const requirementLabels = buildRequirementLabelMap(normalizedJd)
  const evidenceMap = buildEvidenceMap(resumeProfile)

  const recConfig = candidate ? getRecommendationConfig(candidate) : null

  const assessmentInfo = assessmentCandidates?.find(
    (a) =>
      a.id === candidate?.id ||
      (a as any).candidateId === candidate?.id ||
      (a as any).external_candidate_ref === candidate?.id ||
      (candidate?.email && a.email?.trim().toLowerCase() === candidate.email.trim().toLowerCase()) ||
      (candidate?.name && a.candidateName?.trim().toLowerCase() === candidate.name.trim().toLowerCase())
  )

  const rawAssessComp = assessmentInfo?.compositeScore ?? (assessmentInfo as any)?.composite_score ?? (assessmentInfo as any)?.compositescore
  const assessCompScore = rawAssessComp !== undefined && rawAssessComp !== null && rawAssessComp !== '' && !isNaN(Number(rawAssessComp))
    ? Number(rawAssessComp)
    : null
  const assessCompBand = assessmentInfo?.compositeScoreBand || (assessmentInfo as any)?.composite_score_band || (assessmentInfo as any)?.compositescoreband || (assessmentInfo as any)?.score_band

  return (
    <AnimatePresence>
      {candidate && (
        <>
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            className="fixed inset-0 bg-slate-900/30 backdrop-blur-sm z-40"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={onClose}
          />

          {/* Drawer */}
          <motion.div
            key="drawer"
            className="fixed right-0 top-0 bottom-0 w-[500px] bg-white z-50 shadow-2xl flex flex-col overflow-hidden"
            initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 280 }}
          >
            {/* Header */}
            <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between flex-shrink-0 bg-white">
              <div className="flex items-center gap-3">
                <div className="w-11 h-11 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-white font-bold text-[13px] flex-shrink-0 shadow-sm">
                  {candidate.name.split(' ').map((n) => n[0]).join('').slice(0, 2)}
                </div>
                <div>
                  <p className="text-[15px] font-bold text-slate-900">{candidate.name}</p>
                  <p className="text-[11px] text-slate-400 font-medium">{candidate.currentTitle || 'Applicant'}</p>
                </div>
              </div>
              <div className="flex items-center gap-2.5">
                <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors">
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* S.No subheader */}
            <div className="px-6 py-2.5 bg-slate-50 border-b border-slate-100 flex items-center justify-between text-[11px] font-bold text-slate-500">
              <span>S.No {candidate.rank}</span>
            </div>


            {/* Scrollable content */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
              {/* Knockout notice */}
              {candidate.isKnockedOut && (
                <div className="rounded-xl border border-red-200 bg-red-50 p-4 space-y-1">
                  <p className="text-[11px] font-bold uppercase tracking-widest text-red-700">Mandatory Requirement Not Met</p>
                  <p className="text-[13px] font-semibold text-slate-800 mt-1">Candidate does not qualify for this role</p>
                  <p className="text-[12px] text-red-700 mt-1">{candidate.knockoutReason || insights?.recommendation_reason || 'A configured knockout rule was triggered.'}</p>
                </div>
              )}

              {/* Below threshold notice */}
              {!candidate.isKnockedOut && candidate.recommendation === 'REJECT' && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-1">
                  <p className="text-[11px] font-bold uppercase tracking-widest text-amber-700">Not Shortlisted</p>
                  <p className="text-[12px] text-amber-800 mt-1">{insights?.recommendation_reason || 'The candidate does not meet the criteria for this requisition.'}</p>
                </div>
              )}



              {(() => {
                const getDetail = (key: string, fallbackWeight: number) => {
                  const scoreObj = candidate.scores?.find((s) => s.criterionId === key)
                  const bItem = candidate.scoreBreakdown?.find((b) => b.category === key || (key === 'skills' && b.category === 'required_skills'))
                  const weightVal = scoreObj?.weight !== undefined ? scoreObj.weight : (bItem?.effective_weight ?? fallbackWeight)
                  const rawScore = scoreObj?.score ?? bItem?.component_score ?? 0
                  const isInactive = weightVal === 0 || (bItem && !bItem.is_applicable && bItem.effective_weight === 0) || (scoreObj && !scoreObj.isApplicable && scoreObj.weight === 0)
                  const scoreVal = isInactive ? 0 : rawScore
                  const contributionVal = isInactive ? 0 : (scoreObj?.weightedScore ?? bItem?.contribution ?? ((scoreVal * weightVal) / 100))
                  return { scoreVal, weightVal, contributionVal }
                }

                const skillsDetail = getDetail('skills', 50)
                const respDetail = getDetail('responsibilities', 50)
                const skillsPts = Number(skillsDetail.contributionVal)
                const respPts = Number(respDetail.contributionVal)
                const is5050 = (skillsDetail.weightVal === 50 && respDetail.weightVal === 50)
                const totalScore = is5050 ? Number((skillsPts + respPts).toFixed(1)) : Number(candidate.overallScore ?? (skillsPts + respPts))

                return (
                  <>
                    {/* Total Match Score Hero Card (100% Backend Weightage Model) */}
                    <div className="rounded-2xl border border-slate-200/90 bg-gradient-to-br from-slate-50 via-white to-blue-50/30 p-4 shadow-sm space-y-3">
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="text-[10px] font-extrabold uppercase tracking-wider text-slate-500">
                            Total Match Score
                          </span>
                          <div className="flex items-baseline gap-1.5 mt-0.5">
                            <span className="text-3xl font-black tracking-tight text-slate-900">
                              {totalScore.toFixed(1)}%
                            </span>
                            <span className="text-[11px] font-semibold text-slate-400">/ 100</span>
                          </div>
                        </div>

                        {/* Recommendation Status Badge */}
                        <div className="text-right">
                          <span
                            className={`inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-bold uppercase tracking-wider shadow-xs ${
                              candidate.isKnockedOut
                                ? 'bg-red-100 text-red-800 border border-red-200'
                                : candidate.recommendation === 'SHORTLIST'
                                ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                                : candidate.recommendation === 'REVIEW'
                                ? 'bg-amber-100 text-amber-800 border border-amber-200'
                                : 'bg-slate-100 text-slate-700 border border-slate-200'
                            }`}
                          >
                            {candidate.isKnockedOut ? 'Knocked Out' : candidate.recommendation || 'Evaluated'}
                          </span>
                          <p className="text-[9.5px] font-medium text-slate-400 mt-1">
                            Pass Threshold: {candidate.passingScore ?? 70}%
                          </p>
                        </div>
                      </div>

                      {/* Overall Progress Bar */}
                      <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden p-0.5">
                        <motion.div
                          className={`h-full rounded-full ${
                            totalScore >= 70
                              ? 'bg-emerald-500'
                              : totalScore >= 50
                              ? 'bg-blue-600'
                              : 'bg-amber-500'
                          }`}
                          initial={{ width: 0 }}
                          animate={{ width: `${Math.min(100, Math.max(0, totalScore))}%` }}
                          transition={{ duration: 0.6, ease: 'easeOut' }}
                        />
                      </div>

                      {/* 50 + 50 Score Addition Formula */}
                      <div className="pt-2.5 border-t border-slate-100 flex flex-wrap items-center justify-between gap-2 text-[11px]">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <div className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-50 border border-emerald-200/80 text-emerald-900 font-semibold shadow-2xs">
                            <span className="text-slate-600 font-medium text-[11px]">Skills:</span>
                            <span className="font-black text-emerald-700 text-[12.5px]">{skillsPts.toFixed(1)}</span>
                            <span className="text-[10px] font-bold text-slate-400">/ 50</span>
                          </div>
                          <span className="text-slate-400 font-black text-sm px-0.5">+</span>
                          <div className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-blue-50 border border-blue-200/80 text-blue-900 font-semibold shadow-2xs">
                            <span className="text-slate-600 font-medium text-[11px]">Responsibilities:</span>
                            <span className="font-black text-blue-700 text-[12.5px]">{respPts.toFixed(1)}</span>
                            <span className="text-[10px] font-bold text-slate-400">/ 50</span>
                          </div>
                        </div>
                        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-slate-100/90 border border-slate-200/80 font-bold">
                          <span className="text-slate-400 font-bold">=</span>
                          <span className="text-slate-900 font-black text-[13px]">{totalScore.toFixed(1)}</span>
                          <span className="text-[10.5px] text-slate-500 font-semibold">/ 100</span>
                        </div>
                      </div>
                    </div>

                    {/* Backend Component Scoring Breakdown (50 / 50 Model) */}
                    <div className="space-y-2.5">
                      <div className="flex items-center justify-between">
                        <p className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">
                          Component Scoring Breakdown
                        </p>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {/* Skills Card */}
                        <div className="bg-slate-50/80 border border-slate-100 rounded-xl p-2.5 space-y-1.5 hover:border-emerald-200 transition-colors">
                          <div className="flex items-center justify-between gap-1">
                            <span className="text-[11px] text-slate-700 font-bold truncate">
                              Required Skills
                            </span>
                            <div className="flex items-baseline gap-0.5 shrink-0">
                              <span className="text-[13px] font-black text-emerald-700">
                                {skillsPts.toFixed(1)}
                              </span>
                              <span className="text-[10.5px] font-bold text-slate-400">
                                / 50
                              </span>
                            </div>
                          </div>
                          <div className="w-full h-1.5 bg-slate-200/80 rounded-full overflow-hidden">
                            <motion.div
                              className={`h-full rounded-full ${
                                Math.round(skillsDetail.scoreVal) >= 50 ? 'bg-emerald-500' : 'bg-amber-500'
                              }`}
                              initial={{ width: 0 }}
                              animate={{ width: `${Math.min(100, Math.max(0, Math.round(skillsDetail.scoreVal)))}%` }}
                              transition={{ duration: 0.5 }}
                            />
                          </div>
                          <div className="flex items-center justify-between text-[9.5px] text-slate-500">
                            <span>Match: {Math.round(skillsDetail.scoreVal)}%</span>
                            <span>Weight: {Math.round(skillsDetail.weightVal)}% (50 pts)</span>
                          </div>
                        </div>

                        {/* Responsibilities Card */}
                        <div className="bg-slate-50/80 border border-slate-100 rounded-xl p-2.5 space-y-1.5 hover:border-blue-200 transition-colors">
                          <div className="flex items-center justify-between gap-1">
                            <span className="text-[11px] text-slate-700 font-bold truncate">
                              Roles & Responsibilities
                            </span>
                            <div className="flex items-baseline gap-0.5 shrink-0">
                              <span className="text-[13px] font-black text-blue-700">
                                {respPts.toFixed(1)}
                              </span>
                              <span className="text-[10.5px] font-bold text-slate-400">
                                / 50
                              </span>
                            </div>
                          </div>
                          <div className="w-full h-1.5 bg-slate-200/80 rounded-full overflow-hidden">
                            <motion.div
                              className={`h-full rounded-full ${
                                Math.round(respDetail.scoreVal) >= 50 ? 'bg-blue-600' : 'bg-amber-500'
                              }`}
                              initial={{ width: 0 }}
                              animate={{ width: `${Math.min(100, Math.max(0, Math.round(respDetail.scoreVal)))}%` }}
                              transition={{ duration: 0.5 }}
                            />
                          </div>
                          <div className="flex items-center justify-between text-[9.5px] text-slate-500">
                            <span>Match: {Math.round(respDetail.scoreVal)}%</span>
                            <span>Weight: {Math.round(respDetail.weightVal)}% (50 pts)</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </>
                )
              })()}

              {/* Requirement-level AI verdicts and reasoning */}
              {(candidate.matchVerdicts?.length ?? 0) > 0 && (
                <div className="space-y-2.5">
                  <p className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">AI Requirement Evaluation & Reasoning</p>
                  <div className="space-y-2">
                    {candidate.matchVerdicts!.map((verdict) => {
                      const coverageVal = verdict.coverage_score !== undefined 
                        ? verdict.coverage_score 
                        : (verdict.coverage !== undefined 
                            ? verdict.coverage 
                            : (verdict.status === 'MATCHED' ? 1.0 : (verdict.status === 'NO_MATCH' ? 0.0 : 0.5)))
                      const coveragePct = Math.round(coverageVal * 100)
                      const isHighMatch = coverageVal >= 0.85
                      const isPartial = coverageVal >= 0.35 && coverageVal < 0.85
                      const isWeak = coverageVal > 0 && coverageVal < 0.35
                      const isZero = coverageVal === 0

                      const reqText = (verdict as any).requirement_text || requirementLabels.get(verdict.requirement_id) || verdict.requirement_id
                      const imp = (verdict.importance || 'important').toLowerCase()

                      return (
                        <div
                          key={verdict.requirement_id}
                          className={`rounded-xl border p-3.5 space-y-2 transition-all ${
                            isHighMatch
                              ? 'bg-emerald-50/40 border-emerald-100'
                              : isPartial
                              ? 'bg-blue-50/40 border-blue-100'
                              : isWeak
                              ? 'bg-amber-50/30 border-amber-100'
                              : 'bg-rose-50/30 border-rose-100'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="space-y-1">
                              <p className="text-[12px] font-semibold text-slate-800 leading-snug">{reqText}</p>
                              <div className="flex items-center gap-1.5 flex-wrap">
                                {imp === 'critical' && (
                                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-700 border border-red-200 uppercase tracking-wider">
                                    Critical (×3)
                                  </span>
                                )}
                                {imp === 'important' && (
                                  <span className="text-[9px] font-medium px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200">
                                    Important (×2)
                                  </span>
                                )}
                                {imp === 'minor' && (
                                  <span className="text-[9px] font-normal px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
                                    Minor (×1)
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Continuous Coverage Badge */}
                            {verdict.status === 'EVALUATION_FAILED' || verdict.method === 'evaluation_failed' ? (
                              <span className="shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-md tracking-wider bg-amber-100 text-amber-900 border border-amber-300">
                                AI Review Unavailable
                              </span>
                            ) : (
                              <span
                                className={`shrink-0 text-[10px] font-black px-2 py-0.5 rounded-md tracking-wider ${
                                  isHighMatch
                                    ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                                    : isPartial
                                    ? 'bg-blue-100 text-blue-800 border border-blue-200'
                                    : isWeak
                                    ? 'bg-amber-100 text-amber-800 border border-amber-200'
                                    : 'bg-rose-100 text-rose-800 border border-rose-200'
                                }`}
                              >
                                {isHighMatch ? `${coveragePct}% Match` : isPartial ? `Partial ${coveragePct}%` : isWeak ? `Weak ${coveragePct}%` : 'Unmet 0%'}
                              </span>
                            )}
                          </div>

                          {/* Sub-claim atomic breakdown if available */}
                          {verdict.sub_claim_evidence && verdict.sub_claim_evidence.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 pt-0.5">
                              {verdict.sub_claim_evidence.map((sub, idx) => (
                                <span
                                  key={idx}
                                  className={`inline-flex items-center gap-1 text-[9.5px] px-2 py-0.5 rounded-md border font-medium ${
                                    sub.evidence_level === 'direct'
                                      ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                                      : sub.evidence_level === 'adjacent'
                                      ? 'bg-blue-50 text-blue-800 border-blue-200'
                                      : 'bg-slate-100 text-slate-500 border-slate-200 line-through decoration-slate-400'
                                  }`}
                                  title={sub.note || sub.claim}
                                >
                                  <span
                                    className={`w-1.5 h-1.5 rounded-full ${
                                      sub.evidence_level === 'direct'
                                        ? 'bg-emerald-500'
                                        : sub.evidence_level === 'adjacent'
                                        ? 'bg-blue-500'
                                        : 'bg-slate-400'
                                    }`}
                                  />
                                  {sub.claim}
                                </span>
                              ))}
                            </div>
                          )}

                          {verdict.reasoning && (
                            <p className="text-[11px] text-slate-600 leading-relaxed bg-white/80 rounded-lg p-2 border border-slate-100">
                              <span className="font-semibold text-slate-700 mr-1">AI Reason:</span>
                              {verdict.reasoning}
                            </p>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Key matched requirements */}
              {displayStrengths.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <TrendingUp size={13} className="text-emerald-600" />
                    <p className="text-[11px] font-bold text-emerald-700 uppercase tracking-widest">Key Strengths</p>
                  </div>
                  <ul className="space-y-1.5">
                    {displayStrengths.map((s, i) => (
                      <li key={i} className="flex items-start gap-2 text-[12px] text-slate-700">
                        <CheckCircle2 size={13} className="text-emerald-500 flex-shrink-0 mt-0.5" />
                        {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Missing requirements */}
              {displayWeaknesses.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <AlertCircle size={13} className="text-amber-600" />
                    <p className="text-[11px] font-bold text-amber-700 uppercase tracking-widest">Missing / Unclear Qualifications</p>
                  </div>
                  <ul className="space-y-1.5">
                    {displayWeaknesses.map((w, i) => (
                      <li key={i} className="flex items-start gap-2 text-[12px] text-slate-600">
                        <AlertCircle size={13} className="text-amber-500 flex-shrink-0 mt-0.5" />
                        {w}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

// Module-level guard to prevent duplicate background scoring promises
const inFlightScoringProjects = new Set<string>()

function buildCandidateFromScore(
  score: ApiCandidateScore,
  ranking: ApiCandidateRanking | undefined,
  config: WeightConfig,
  fallbackName: string,
  fallbackEmail: string,
  filename: string,
): Candidate {
  const components = [
    ['skills', 'Required Skills'],
    ['responsibilities', 'Responsibilities'],
    ['projects', 'Projects'],
    ['preferred_skills', 'Preferred Skills'],
    ['experience', 'Experience'],
    ['certifications', 'Certifications'],
    ['education', 'Education'],
    ['languages', 'Languages'],
  ] as const

  const candidateScores = components
    .map(([key, label]) => {
      const detail = (score.component_scores as any)?.[key]
      if (!detail) return null
      const explanation = detail.explanation || ''
      const isApplicable = !(/\(N\/A\)/i.test(explanation) || (key === 'experience' && /against 0 required months/i.test(explanation)))
      const weightKey = key === 'skills' ? 'required_skills' : key
      const effectiveWeight = (score.effective_weights && (score.effective_weights[weightKey] ?? score.effective_weights[key])) ?? (config.weights as any)?.[key] ?? (key === 'skills' ? 50 : key === 'responsibilities' ? 50 : 0)
      const finalScore = (effectiveWeight === 0 || !isApplicable) ? 0 : (detail.score ?? 0)
      const weightedScore = (score.weighted_scores as any)?.[key] ?? (finalScore * effectiveWeight / 100)
      return {
        criterionId: key,
        label,
        score: finalScore,
        weight: effectiveWeight,
        weightedScore,
        isApplicable,
        explanation,
      }
    })
    .filter(Boolean) as any[]

  const skillsObj = candidateScores.find((s) => s.criterionId === 'skills')
  const respObj = candidateScores.find((s) => s.criterionId === 'responsibilities')
  const is5050 = skillsObj?.weight === 50 && respObj?.weight === 50
  const direct5050Score = is5050 && skillsObj && respObj
    ? Number((skillsObj.weightedScore + respObj.weightedScore).toFixed(1))
    : (ranking?.final_score ?? score.final_score)

  const recommendation = ranking?.recommendation ?? score.recommendation
  const isKnockedOut = ranking?.is_knocked_out ?? score.is_knocked_out
  const knockoutReason = ranking?.knockout_reason ?? score.knockout_reason

  return {
    id: score.document_id,
    documentId: score.document_id,
    name: ranking?.candidate_name || fallbackName || 'Candidate',
    email: ranking?.email || fallbackEmail || '',
    resumeFile: filename || score.document_id,
    overallScore: direct5050Score,
    rank: ranking?.rank_position ?? 1,
    percentile: ranking?.percentile ?? score.confidence,
    confidence: ranking?.confidence ?? score.confidence,
    recommendation,
    isKnockedOut,
    knockoutReason,
    rejectionReason: isKnockedOut ? 'knockout' : recommendation === 'REJECT' ? 'below_recommendation_threshold' : undefined,
    status: recommendationToStatus(recommendation, isKnockedOut, direct5050Score),
    extractedFields: [],
    scores: candidateScores,
    matchVerdicts: score.match_verdicts || (score as any).matchVerdicts || [],
    passingScore: score.passing_score ?? config.passing_score,
    effectiveWeights: score.effective_weights,
    scoreBreakdown: score.score_breakdown || [],
    scoredAt: new Date(score.created_at || (ranking?.created_at ?? Date.now())),
    isProcessing: false,
  }
}

function buildPendingCandidate(
  docId: string,
  fallbackName: string,
  fallbackEmail: string,
  filename: string,
): Candidate {
  return {
    id: docId,
    documentId: docId,
    name: fallbackName || filename || 'Candidate',
    email: fallbackEmail || '',
    resumeFile: filename || docId,
    overallScore: -1,
    rank: 999,
    recommendation: 'PENDING',
    isKnockedOut: false,
    status: 'pending',
    extractedFields: [],
    scores: [],
    isProcessing: true,
  }
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function CandidateRanking() {
  const { state, dispatch } = usePipeline()
  const navigate = useNavigate()
  const location = useLocation()

  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState<ScreeningStatus | 'all'>('all')
  const [sortBy, setSortBy] = useState<'rank' | 'score'>('rank')
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null)
  const [rankingsLoading, setRankingsLoading] = useState(true)
  const [requestedDocumentId] = useState(() => (location.state as { selectedDocumentId?: string } | null)?.selectedDocumentId)

  // Live scoring state
  const [isScoringInProgress, setIsScoringInProgress] = useState(false)
  const [scoringProgress, setScoringProgress] = useState<{ completed: number; total: number }>({ completed: 0, total: 0 })
  const [scoringError, setScoringError] = useState<string | null>(null)
  const pollIntervalRef = React.useRef<NodeJS.Timeout | null>(null)

  const candidates: Candidate[] = state.candidates

  // Auto-open drawer if navigated with a specific document
  useEffect(() => {
    if (!requestedDocumentId || selectedCandidate) return
    const requested = candidates.find((c) => c.documentId === requestedDocumentId)
    if (requested) setSelectedCandidate(requested)
  }, [candidates, requestedDocumentId, selectedCandidate])

  const dummyConfig = React.useMemo<WeightConfig>(() => ({
    id: '',
    project_id: state.projectId || '',
    weights: { required_skills: 50, responsibilities: 50, preferred_skills: 0, projects: 0, experience: 0, education: 0, certifications: 0, languages: 0 },
    passing_score: 60,
    min_experience_years: 0,
    required_degree: null,
    required_certifications: [],
    mandatory_skills: [],
    preferred_skills: [],
    knockout_rules: [],
    custom_keywords: [],
    version: 1,
    created_at: '',
    updated_at: '',
  }), [state.projectId])

  const buildCandidateMap = useCallback((
    documents: ApiDocument[],
    scores: ApiCandidateScore[],
    rankings: ApiCandidateRanking[],
    metaMap: Map<string, { name: string; email: string; filename: string }>
  ): Candidate[] => {
    const scoresByDoc = new Map(scores.map((s) => [s.document_id, s]))
    const rankingsByDoc = new Map(rankings.map((r) => [r.document_id, r]))

    const result: Candidate[] = []

    for (const doc of documents) {
      const meta = metaMap.get(doc.id)
      const filename = meta?.filename || doc.original_filename
      const fallbackName = meta?.name || filename.replace(/\.[^/.]+$/, '').replace(/[_-]/g, ' ')
      const fallbackEmail = meta?.email || ''

      const s = scoresByDoc.get(doc.id)
      const r = rankingsByDoc.get(doc.id)

      if (s) {
        result.push(buildCandidateFromScore(s, r, dummyConfig, fallbackName, fallbackEmail, filename))
      } else {
        result.push(buildPendingCandidate(doc.id, fallbackName, fallbackEmail, filename))
      }
    }

    // Sort: scored candidates by rank or score descending, then pending candidates
    return result.sort((a, b) => {
      if (a.isProcessing && !b.isProcessing) return 1
      if (!a.isProcessing && b.isProcessing) return -1
      if (!a.isProcessing && !b.isProcessing) {
        if (a.rank && b.rank && a.rank !== b.rank && rankings.length > 0) return a.rank - b.rank
        return b.overallScore - a.overallScore
      }
      return 0
    })
  }, [dummyConfig])

  // Orchestrate progressive scoring and ranking
  const startScoringFlow = useCallback(async (forceRetry = false) => {
    if (!state.projectId) {
      setRankingsLoading(false)
      return
    }

    const projectId = state.projectId
    setScoringError(null)

    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }

    try {
      // 1. Fetch current documents, scores, and rankings
      const [resumesRes, initialScoresRes, initialRankingsRes] = await Promise.all([
        api.listProjectResumes(projectId).catch(() => ({ items: [], total: 0 })),
        api.getProjectScores(projectId).catch(() => []),
        api.getRankings(projectId, { page_size: 100 }).catch(() => ({ items: [], total: 0 })),
      ])

      const docList: ApiDocument[] = resumesRes.items || []
      const initialScores: ApiCandidateScore[] = Array.isArray(initialScoresRes) ? initialScoresRes : []
      const initialRankings: ApiCandidateRanking[] = Array.isArray(initialRankingsRes.items) ? initialRankingsRes.items : []

      if (docList.length === 0) {
        setRankingsLoading(false)
        setIsScoringInProgress(false)
        return
      }

      // Metadata lookup map (names, emails)
      const metaMap = new Map<string, { name: string; email: string; filename: string }>()
      for (const r of state.upload.resumes) {
        metaMap.set(r.id, {
          name: r.name ? r.name.replace(/\.[^/.]+$/, '').replace(/[_-]/g, ' ') : 'Candidate',
          email: '',
          filename: r.name,
        })
      }

      // Attempt to load candidate names from normalized documents
      try {
        const normDocs = await Promise.all(
          docList.map(async (doc) => {
            try {
              const res = await api.getNormalizedDocument(doc.id)
              const data = (res && 'data' in res) ? (res as any).data : res
              return { id: doc.id, data }
            } catch {
              return null
            }
          })
        )
        for (const item of normDocs) {
          if (item && item.data && typeof item.data === 'object' && item.data.candidate_name) {
            metaMap.set(item.id, {
              name: item.data.candidate_name,
              email: item.data.email || '',
              filename: metaMap.get(item.id)?.filename || '',
            })
          }
        }
      } catch {
        // Fallback to filenames
      }

      // Check if scoring is already 100% complete
      const isComplete = !forceRetry &&
        initialScores.length >= docList.length &&
        initialRankings.length >= docList.length

      if (isComplete) {
        const mapped = buildCandidateMap(docList, initialScores, initialRankings, metaMap)
        const existingStatusMap = new Map(state.candidates.map((c) => [c.id, c.status]))
        const merged = mapped.map((c) => {
          const overrideStatus = existingStatusMap.get(c.id)
          return overrideStatus !== undefined ? { ...c, status: overrideStatus } : c
        })
        dispatch({ type: 'SET_RANKED_CANDIDATES', payload: merged })
        setRankingsLoading(false)
        setIsScoringInProgress(false)
        setScoringProgress({ completed: initialScores.length, total: docList.length })
        return
      }

      // Scoring is needed or in progress!
      // Immediately render candidates with existing scores or pending state
      const initialMapped = buildCandidateMap(docList, initialScores, initialRankings, metaMap)
      const existingStatusMap = new Map(state.candidates.map((c) => [c.id, c.status]))
      const initialMerged = initialMapped.map((c) => {
        const overrideStatus = existingStatusMap.get(c.id)
        return overrideStatus !== undefined ? { ...c, status: overrideStatus } : c
      })
      dispatch({ type: 'SET_RANKED_CANDIDATES', payload: initialMerged })
      setRankingsLoading(false)
      setIsScoringInProgress(true)
      setScoringProgress({ completed: initialScores.length, total: docList.length })

      // Trigger background scoring if not already running for this project
      if (!inFlightScoringProjects.has(projectId) || forceRetry) {
        inFlightScoringProjects.add(projectId)
        api.scoreProject(projectId)
          .then(async () => {
            await api.rankProject(projectId)
          })
          .catch((err) => {
            console.error('Backend scoring error:', err)
            setScoringError(err instanceof Error ? err.message : 'Candidate scoring failed. Please retry.')
          })
          .finally(() => {
            inFlightScoringProjects.delete(projectId)
          })
      }

      // Start polling getProjectScores every 2500ms
      pollIntervalRef.current = setInterval(async () => {
        try {
          const [currentScores, currentRankings] = await Promise.all([
            api.getProjectScores(projectId).catch(() => []),
            api.getRankings(projectId, { page_size: 100 }).catch(() => ({ items: [], total: 0 })),
          ])

          const activeScores: ApiCandidateScore[] = Array.isArray(currentScores) ? currentScores : []
          const activeRankings: ApiCandidateRanking[] = Array.isArray(currentRankings.items) ? currentRankings.items : []

          setScoringProgress({ completed: activeScores.length, total: docList.length })

          // Progressively update candidates in UI
          const updatedMapped = buildCandidateMap(docList, activeScores, activeRankings, metaMap)
          const currentStatusMap = new Map(state.candidates.map((c) => [c.id, c.status]))
          const updatedMerged = updatedMapped.map((c) => {
            const overrideStatus = currentStatusMap.get(c.id)
            return overrideStatus !== undefined ? { ...c, status: overrideStatus } : c
          })
          dispatch({ type: 'SET_RANKED_CANDIDATES', payload: updatedMerged })

          // Check completion
          const isDone = (!inFlightScoringProjects.has(projectId) && activeScores.length >= docList.length)
          if (isDone) {
            if (pollIntervalRef.current) {
              clearInterval(pollIntervalRef.current)
              pollIntervalRef.current = null
            }
            // Ensure rank is computed
            try {
              await api.rankProject(projectId)
              const [finalRanks, finalScs] = await Promise.all([
                api.getRankings(projectId, { page_size: 100 }),
                api.getProjectScores(projectId),
              ])
              const finalMapped = buildCandidateMap(docList, finalScs || [], finalRanks.items || [], metaMap)
              dispatch({ type: 'SET_RANKED_CANDIDATES', payload: finalMapped })
            } catch {
              // Ignore ranking fallback error
            }
            setIsScoringInProgress(false)
          } else if (!inFlightScoringProjects.has(projectId) && activeScores.length < docList.length) {
            if (pollIntervalRef.current) {
              clearInterval(pollIntervalRef.current)
              pollIntervalRef.current = null
            }
            setIsScoringInProgress(false)
          }
        } catch (pollErr) {
          console.warn('Poll error:', pollErr)
        }
      }, 2500)

    } catch (err) {
      setRankingsLoading(false)
      setIsScoringInProgress(false)
      setScoringError(err instanceof Error ? err.message : 'Failed to initialize candidate shortlisting.')
    }
  }, [buildCandidateMap, dispatch, state.candidates, state.projectId, state.upload.resumes])

  useEffect(() => {
    void startScoringFlow()
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }
  }, [state.projectId])


  // Derived data
  const filtered = candidates
    .filter((c) => {
      const q = search.toLowerCase()
      const matchSearch = c.name.toLowerCase().includes(q) || c.email.toLowerCase().includes(q)
      const matchStatus = filterStatus === 'all' || c.status === filterStatus
      return matchSearch && matchStatus
    })
    .sort((a, b) => {
      if (b.overallScore !== a.overallScore) {
        return b.overallScore - a.overallScore
      }
      return a.rank - b.rank
    })

  const shortlisted = candidates.filter((c) => c.status === 'screened').length
  const needsReview = candidates.filter((c) => c.status === 'pending').length
  const rejected = candidates.filter((c) => c.status === 'rejected').length
  const avgScore = candidates.length ? Math.round(candidates.reduce((s, c) => s + c.overallScore, 0) / candidates.length) : 0

  const updateStatus = (id: string, status: ScreeningStatus) =>
    dispatch({ type: 'UPDATE_CANDIDATE_STATUS', payload: { id, status } })

  const handleGoToShortlist = () => {
    if (state.projectId) {
      navigate(`/projects/${state.projectId}/shortlist`)
    } else {
      navigate('/departments')
    }
  }

  return (
    <>
      {/* Explanation Drawer */}
      <ExplanationDrawer
        candidate={selectedCandidate}
        projectId={state.projectId}
        jdDocumentId={state.jdDocumentId}
        assessmentCandidates={state.assessmentCandidates}
        onClose={() => setSelectedCandidate(null)}
      />

      <motion.div variants={container} initial="hidden" animate="show" className="w-full max-w-7xl mx-auto space-y-6 pb-10">

        {/* ── Page Header ── */}
        <motion.div variants={fadeUp} className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">Candidate Rankings</h1>
            <p className="text-xs text-slate-500 mt-1 max-w-2xl leading-relaxed">
              AI candidate evaluation and relevance rankings based on job requirements and screening criteria.
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <select
              className="text-xs border border-slate-200 rounded-xl px-3 py-2 text-slate-600 outline-none bg-white font-semibold hover:border-slate-300 transition-colors shadow-2xs cursor-pointer"
              onChange={async (e) => {
                const val = e.target.value as 'csv' | 'excel' | 'json' | ''
                if (!val || !state.projectId) return
                try {
                  const blob = await api.exportProjectData(state.projectId, val as any)
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = `rankings_${state.projectId}.${val === 'excel' ? 'xlsx' : val}`
                  a.click()
                  URL.revokeObjectURL(url)
                } catch { /* mock mode — export silently fails */ }
                e.target.value = ''
              }}
              defaultValue=""
            >
              <option value="" disabled>Export</option>
              <option value="csv">Export CSV</option>
              <option value="excel">Export Excel</option>
              <option value="json">Export JSON</option>
            </select>
            <motion.button
              onClick={handleGoToShortlist}
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white rounded-xl text-xs font-bold hover:bg-blue-700 transition-colors shadow-sm cursor-pointer"
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
            >
              <UserCheck size={14} />
              Go to Shortlist
              <ArrowRight size={13} />
            </motion.button>
          </div>
        </motion.div>

        {/* ── AI Evaluation In Progress Banner ── */}
        {isScoringInProgress && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-4 rounded-2xl bg-gradient-to-r from-blue-50/90 via-sky-50/80 to-indigo-50/90 border border-blue-200/80 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-4"
          >
            <div className="flex items-center gap-3.5">
              <div className="w-10 h-10 rounded-xl bg-blue-600 text-white flex items-center justify-center shrink-0 shadow-sm">
                <Loader2 size={20} className="animate-spin" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold text-slate-900">
                    Candidate Scoring & AI Evaluation in Progress
                  </h3>
                  <span className="px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 text-[10px] font-extrabold uppercase tracking-wider">
                    Live
                  </span>
                </div>
                <p className="text-xs text-slate-600 mt-0.5">
                  Evaluating candidate resumes against job requirements and responsibilities. Results update automatically.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0 self-end sm:self-center">
              <div className="text-right">
                <span className="text-xs font-bold text-slate-900">
                  {scoringProgress.completed} of {scoringProgress.total}
                </span>
                <span className="text-[11px] text-slate-500 ml-1 font-medium">completed</span>
              </div>
              <div className="w-28 h-2 bg-blue-200/60 rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-blue-600 rounded-full transition-all duration-500"
                  style={{
                    width: `${scoringProgress.total > 0 ? (scoringProgress.completed / scoringProgress.total) * 100 : 0}%`,
                  }}
                />
              </div>
            </div>
          </motion.div>
        )}

        {/* ── Scoring Error Banner with Retry ── */}
        {scoringError && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-4 rounded-2xl bg-red-50 border border-red-200 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-red-800"
          >
            <div className="flex items-center gap-3">
              <AlertCircle size={20} className="text-red-600 shrink-0" />
              <div>
                <p className="text-xs font-bold">Candidate evaluation encountered an issue</p>
                <p className="text-xs text-red-600 mt-0.5">{scoringError}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => void startScoringFlow(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-red-600 hover:bg-red-700 text-white text-xs font-bold shadow-xs cursor-pointer transition-colors shrink-0"
            >
              <RefreshCw size={13} />
              <span>Retry Scoring</span>
            </button>
          </motion.div>
        )}

        {/* ── Candidate Table ── */}
        <motion.div variants={fadeUp} className="bg-white border border-slate-200/90 rounded-2xl shadow-xs overflow-hidden">

          {/* Toolbar */}
          <div className="flex items-center gap-3 px-6 py-4 border-b border-slate-100 bg-slate-50/50">
            <div className="flex items-center gap-2 flex-1 bg-white rounded-xl px-3.5 py-2 border border-slate-200/90 shadow-2xs">
              <Search size={14} className="text-slate-400 shrink-0" />
              <input
                type="text"
                placeholder="Search candidates by name or email…"
                className="bg-transparent outline-none text-xs text-slate-700 flex-1 placeholder-slate-400 font-medium"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch('')}
                  className="text-slate-400 hover:text-slate-600 text-xs"
                >
                  <X size={13} />
                </button>
              )}
            </div>

            <select
              className="text-xs font-semibold border border-slate-200/90 rounded-xl px-3.5 py-2 text-slate-700 outline-none bg-white shadow-2xs cursor-pointer"
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as ScreeningStatus | 'all')}
            >
              <option value="all">All Candidates</option>
              <option value="screened">Shortlisted</option>
              <option value="pending">Under Review</option>
              <option value="rejected">Not Relevant</option>
            </select>
          </div>

          {/* Table */}
          {rankingsLoading ? (
            <div className="py-16 text-center text-slate-400">
              <motion.div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-3"
                animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }} />
              <p className="text-xs font-medium">Loading candidate rankings…</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/40 text-left">
                    <th className="px-6 py-4 text-[11px] font-bold text-slate-400 uppercase tracking-wider">Candidate</th>
                    <th className="px-6 py-4 text-[11px] font-bold text-slate-400 uppercase tracking-wider w-72">Score & Band</th>
                    <th className="px-6 py-4 text-[11px] font-bold text-slate-400 uppercase tracking-wider text-center w-48">Screening Status</th>
                    <th className="px-6 py-4 text-[11px] font-bold text-slate-400 uppercase tracking-wider text-right w-36">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  <AnimatePresence>
                    {filtered.map((candidate, idx) => {
                      const recConfig = getRecommendationConfig(candidate)

                      return (
                        <motion.tr
                          key={candidate.id}
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0 }}
                          transition={{ delay: idx * 0.03 }}
                          className={`${candidate.isProcessing ? 'bg-slate-50/40 cursor-default' : 'hover:bg-slate-50/70 cursor-pointer'} transition-colors group`}
                          onClick={() => {
                            if (!candidate.isProcessing) setSelectedCandidate(candidate)
                          }}
                        >
                          {/* Candidate */}
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3.5">
                              <div className="w-10 h-10 rounded-full bg-slate-100 border border-slate-200/80 flex items-center justify-center text-slate-700 font-bold text-xs shrink-0 shadow-2xs">
                                {candidate.name.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase() || 'C'}
                              </div>
                              <div className="min-w-0">
                                <div className="font-bold text-slate-900 text-sm truncate group-hover:text-blue-600 transition-colors">
                                  {candidate.name}
                                </div>
                                <div className="text-xs text-slate-500 font-normal truncate mt-0.5">
                                  {candidate.email || candidate.resumeFile}
                                </div>
                              </div>
                            </div>
                          </td>

                          {/* Score & Band */}
                          <td className="px-6 py-4">
                            {candidate.isProcessing ? (
                              <div className="flex items-center gap-2.5">
                                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-blue-50/90 border border-blue-200/80 text-blue-700 text-xs font-semibold">
                                  <Loader2 size={13} className="animate-spin text-blue-600 shrink-0" />
                                  <span>Scoring…</span>
                                </div>
                                <span className="px-2.5 py-1 rounded-lg text-xs font-bold inline-flex items-center gap-1.5 border border-amber-200 bg-amber-50 text-amber-700 shadow-2xs">
                                  <HelpCircle size={13} className="text-amber-500" />
                                  <span>Under Review</span>
                                </span>
                              </div>
                            ) : (
                              <div className="flex items-center gap-3.5">
                                <div className="flex flex-col">
                                  <div className="flex items-baseline gap-1">
                                    <span className="text-base font-extrabold text-slate-900 leading-none">
                                      {Math.round(candidate.overallScore)}%
                                    </span>
                                  </div>
                                  <div className="w-16 h-1.5 bg-slate-100 rounded-full mt-1.5 overflow-hidden">
                                    <div
                                      className={`h-full rounded-full transition-all duration-500 ${
                                        candidate.overallScore >= 70
                                          ? 'bg-emerald-500'
                                          : candidate.overallScore >= 45
                                          ? 'bg-amber-500'
                                          : 'bg-rose-500'
                                      }`}
                                      style={{ width: `${Math.min(100, Math.max(0, candidate.overallScore))}%` }}
                                    />
                                  </div>
                                </div>
                                <div className={`px-2.5 py-1 rounded-lg text-xs font-bold inline-flex items-center gap-1.5 border shadow-2xs ${recConfig.cls}`}>
                                  <recConfig.Icon size={13} className={recConfig.iconColor} />
                                  <span>{recConfig.label}</span>
                                </div>
                              </div>
                            )}
                          </td>

                          {/* Screening Status */}
                          <td className="px-6 py-4 text-center" onClick={(e) => e.stopPropagation()}>
                            {candidate.isProcessing ? (
                              <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-amber-50 text-amber-800 border border-amber-300 shadow-2xs">
                                <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                                <span>Under Review</span>
                              </span>
                            ) : (
                              <select
                                className={`text-xs font-bold border rounded-xl px-3.5 py-2 outline-none transition-all cursor-pointer shadow-2xs ${
                                  candidate.status === 'screened'
                                    ? 'bg-emerald-50 text-emerald-800 border-emerald-300 hover:bg-emerald-100/80'
                                    : candidate.status === 'pending'
                                    ? 'bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100/80'
                                    : 'bg-rose-50 text-rose-800 border-rose-300 hover:bg-rose-100/80'
                                }`}
                                value={candidate.status}
                                onChange={(e) => {
                                  e.stopPropagation()
                                  updateStatus(candidate.id, e.target.value as ScreeningStatus)
                                }}
                              >
                                <option value="screened" className="bg-white text-slate-800 font-semibold">Shortlisted</option>
                                <option value="pending" className="bg-white text-slate-800 font-semibold">Under Review</option>
                                <option value="rejected" className="bg-white text-slate-800 font-semibold">Not Relevant</option>
                              </select>
                            )}
                          </td>

                          {/* Explain / View Details */}
                          <td className="px-6 py-4 text-right" onClick={(e) => e.stopPropagation()}>
                            {candidate.isProcessing ? (
                              <span className="text-[11px] text-slate-400 font-medium italic">
                                Pending AI review
                              </span>
                            ) : (
                              <motion.button
                                type="button"
                                className="inline-flex items-center gap-1.5 text-xs font-bold text-blue-600 hover:text-blue-700 px-3.5 py-2 rounded-xl hover:bg-blue-50 border border-blue-200/80 bg-white transition-all shadow-2xs cursor-pointer"
                                onClick={(e) => { e.stopPropagation(); setSelectedCandidate(candidate) }}
                                whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}
                              >
                                <Sparkles size={13} className="text-blue-500" />
                                <span>Explain</span>
                              </motion.button>
                            )}
                          </td>
                        </motion.tr>
                      )
                    })}
                  </AnimatePresence>
                </tbody>
              </table>

              {!rankingsLoading && filtered.length === 0 && (
                <div className="py-14 text-center text-slate-400">
                  <Users size={28} className="mx-auto mb-3 opacity-25" />
                  <p className="text-xs font-medium">
                    {search || filterStatus !== 'all' ? 'No candidates match your filter.' : 'No candidates have been ranked yet.'}
                  </p>
                  {(search || filterStatus !== 'all') && (
                    <button onClick={() => { setSearch(''); setFilterStatus('all') }} className="mt-2 text-xs text-blue-500 hover:underline cursor-pointer">
                      Clear filters
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </motion.div>

      </motion.div>
    </>
  )
}
