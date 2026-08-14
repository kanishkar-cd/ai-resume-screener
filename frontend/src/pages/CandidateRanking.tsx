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
  if (candidate.isKnockedOut || candidate.recommendation === 'REJECT') {
    return {
      label: 'Not Relevant',
      shortLabel: 'Reject',
      cls: 'bg-red-50 text-red-700 border border-red-200',
      iconColor: 'text-red-400',
      Icon: ThumbsDown,
    }
  }
  if (candidate.recommendation === 'SHORTLIST') {
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

function recommendationToStatus(recommendation: string, knockedOut: boolean): ScreeningStatus {
  if (knockedOut || recommendation === 'REJECT') return 'rejected'
  if (recommendation === 'SHORTLIST') return 'screened'
  return 'pending'
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
  onClose: () => void
}

function ExplanationDrawer({ candidate, projectId, jdDocumentId, onClose }: ExplanationDrawerProps) {
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
                <div className={`px-3 py-1.5 rounded-xl text-[13px] font-extrabold border ${getScoreBg(candidate.overallScore)} ${getScoreColor(candidate.overallScore)}`}>
                  {candidate.overallScore} / 100
                </div>
                <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors">
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Recommendation banner */}
            {recConfig && (
              <div className={`px-6 py-3 flex items-center gap-2.5 border-b text-[12px] font-bold ${recConfig.cls}`}>
                <recConfig.Icon size={14} className={recConfig.iconColor} />
                <span>{recConfig.label} — {recConfig.shortLabel}</span>
                <span className="ml-auto font-normal text-[11px] opacity-70">Rank #{candidate.rank}</span>
              </div>
            )}

            {/* Scrollable content */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
              {/* Candidate profile (from backend, if available) */}
              {loadingProfile && <div className="rounded-xl border border-slate-200 p-4 text-[12px] text-slate-500">Loading candidate profile…</div>}
              {profileError && <div className="rounded-xl border border-amber-100 bg-amber-50 p-4 text-[12px] text-amber-700">Profile unavailable: {profileError}</div>}
              {resumeProfile && <CandidateProfile normalized={resumeProfile.normalized} extracted={resumeProfile.extracted} document={resumeProfile.document} />}

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
                  <p className="text-[11px] font-bold uppercase tracking-widest text-amber-700">Below Screening Threshold</p>
                  <p className="text-[12px] text-amber-800 mt-1">{insights?.recommendation_reason || 'The candidate\'s match score did not meet the minimum threshold for this requisition.'}</p>
                  <p className="border-t border-amber-200 pt-2 mt-2 text-[12px] text-slate-600">
                    Match Score <span className="font-bold text-slate-800">{candidate.overallScore} / 100</span>
                  </p>
                </div>
              )}

              {/* Why this candidate matches */}
              <div className="rounded-xl bg-gradient-to-br from-blue-50 to-slate-50 border border-blue-100 p-5">
                <div className="flex items-center gap-2 mb-3">
                  <Sparkles size={14} className="text-blue-500" />
                  <p className="text-[11px] font-bold text-blue-600 uppercase tracking-widest">
                    Why this candidate {loadingInsights ? '(Loading...)' : ''}
                  </p>
                </div>
                <p className="text-[13px] text-slate-700 leading-relaxed">{aiSummaryText}</p>
                {insights?.score_explanation && (
                  <p className="mt-2 text-[12px] text-slate-500 italic">{insights.score_explanation}</p>
                )}
              </div>

              {/* Key matched requirements */}
              {displayStrengths.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <TrendingUp size={13} className="text-emerald-500" />
                    <p className="text-[11px] font-bold text-emerald-600 uppercase tracking-widest">Key Matched Requirements</p>
                  </div>
                  <ul className="space-y-1.5">
                    {displayStrengths.map((s, i) => (
                      <motion.li key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.1 + i * 0.05 }}
                        className="flex items-start gap-2 text-[12.5px] text-slate-700">
                        <CheckCircle2 size={13} className="text-emerald-500 flex-shrink-0 mt-0.5" />
                        {s}
                      </motion.li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Missing requirements */}
              {displayWeaknesses.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <AlertCircle size={13} className="text-amber-500" />
                    <p className="text-[11px] font-bold text-amber-600 uppercase tracking-widest">Missing / Unclear Requirements</p>
                  </div>
                  <ul className="space-y-1.5">
                    {displayWeaknesses.map((w, i) => (
                      <motion.li key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.15 + i * 0.05 }}
                        className="flex items-start gap-2 text-[12.5px] text-slate-600">
                        <AlertCircle size={13} className="text-amber-400 flex-shrink-0 mt-0.5" />
                        {w}
                      </motion.li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 50 + 50 Score Model Breakdown */}
              <div>
                <p className="text-[11px] font-bold text-slate-500 uppercase tracking-widest mb-3">Evaluation Score Breakdown (50 + 50 Model)</p>
                
                {(() => {
                  const skillScoreObj = candidate.scores.find((s) => s.criterionId === 'skills')
                  const skillScore50 = Math.round(((skillScoreObj?.score ?? 0) / 100) * 50)
                  const nonSkillScores = candidate.scores.filter((s) => s.criterionId !== 'skills')
                  const avgNonSkill = nonSkillScores.length
                    ? nonSkillScores.reduce((acc, curr) => acc + curr.score, 0) / nonSkillScores.length
                    : candidate.overallScore
                  const aiRelevance50 = Math.round((avgNonSkill / 100) * 50)

                  return (
                    <div className="space-y-3">
                      {/* Skill Match (50) */}
                      <div className="bg-blue-50/60 border border-blue-100 rounded-xl p-3.5 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-[12px] text-slate-800 font-bold">1. Deterministic Skill Match</span>
                          <span className="text-[13px] font-extrabold text-blue-700">{skillScore50} / 50 Marks</span>
                        </div>
                        <div className="w-full h-2 bg-blue-100 rounded-full overflow-hidden">
                          <motion.div
                            className="h-full rounded-full bg-blue-600"
                            initial={{ width: 0 }}
                            animate={{ width: `${(skillScore50 / 50) * 100}%` }}
                            transition={{ duration: 0.5 }}
                          />
                        </div>
                        <p className="text-[10px] text-slate-500">Calculated from matched required skills against JD requirements.</p>
                      </div>

                      {/* AI Relevance (50) */}
                      <div className="bg-emerald-50/60 border border-emerald-100 rounded-xl p-3.5 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-[12px] text-slate-800 font-bold">2. AI JD Relevance & Evidence</span>
                          <span className="text-[13px] font-extrabold text-emerald-700">{aiRelevance50} / 50 Marks</span>
                        </div>
                        <div className="w-full h-2 bg-emerald-100 rounded-full overflow-hidden">
                          <motion.div
                            className="h-full rounded-full bg-emerald-600"
                            initial={{ width: 0 }}
                            animate={{ width: `${(aiRelevance50 / 50) * 100}%` }}
                            transition={{ duration: 0.5, delay: 0.1 }}
                          />
                        </div>
                        <p className="text-[10px] text-slate-500">LLM evaluation of candidate projects, experience, education, and evidence against JD context.</p>
                      </div>
                    </div>
                  )
                })()}

                {/* Final score */}
                <div className="mt-3 rounded-xl bg-slate-900 text-white p-4 flex items-center justify-between shadow-sm">
                  <div>
                    <p className="text-[12px] font-bold text-slate-300">Final Score</p>
                    <p className="text-[10px] text-slate-400">Skill Match (50) + AI Relevance (50)</p>
                  </div>
                  <p className="text-[26px] font-extrabold text-white">
                    {candidate.overallScore}
                    <span className="text-[13px] font-normal text-slate-400 ml-1">/ 100</span>
                  </p>
                </div>
              </div>

              {/* Requirement-level verdicts (collapsed section) */}
              {(candidate.matchVerdicts?.length ?? 0) > 0 && (
                <div>
                  <p className="text-[11px] font-bold text-slate-500 uppercase tracking-widest mb-3">Requirement Matches</p>
                  <div className="space-y-2">
                    {candidate.matchVerdicts!.filter(v => v.status === 'MATCHED').map((verdict) => (
                      <div key={verdict.requirement_id} className={`rounded-lg border px-3 py-2.5 flex items-center justify-between gap-3 ${verdictStatusClass(verdict.status)}`}>
                        <p className="text-[12px] font-medium">{requirementLabels.get(verdict.requirement_id) || verdict.requirement_id}</p>
                        <span className="shrink-0 text-[10px] font-bold uppercase">{verdictStatusLabel(verdict.status)}</span>
                      </div>
                    ))}
                    {candidate.matchVerdicts!.filter(v => v.status === 'NO_MATCH').map((verdict) => (
                      <div key={verdict.requirement_id} className={`rounded-lg border px-3 py-2.5 flex items-center justify-between gap-3 ${verdictStatusClass(verdict.status)}`}>
                        <p className="text-[12px] font-medium">{requirementLabels.get(verdict.requirement_id) || verdict.requirement_id}</p>
                        <span className="shrink-0 text-[10px] font-bold uppercase">{verdictStatusLabel(verdict.status)}</span>
                      </div>
                    ))}
                  </div>
                  {jdError && <p className="mt-2 text-[11px] text-amber-600">JD details unavailable: {jdError}</p>}
                  {(loadingJd || loadingProfile) && <p className="mt-2 text-[11px] text-slate-400">Loading requirements…</p>}
                </div>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
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

  const candidates: Candidate[] = state.candidates

  // Auto-open drawer if navigated with a specific document
  useEffect(() => {
    if (!requestedDocumentId || selectedCandidate) return
    const requested = candidates.find((c) => c.documentId === requestedDocumentId)
    if (requested) setSelectedCandidate(requested)
  }, [candidates, requestedDocumentId, selectedCandidate])

  const mapRankings = useCallback((rankings: ApiCandidateRanking[], scores: ApiCandidateScore[], config: WeightConfig): Candidate[] => {
    const scoresByDocument = new Map(scores.map((score) => [score.document_id, score]))
    const components = [
      ['skills', 'Skills'], ['experience', 'Experience'], ['projects', 'Projects'],
      ['education', 'Education'], ['certifications', 'Certifications'], ['languages', 'Languages'],
    ] as const
    return rankings.map((ranking) => {
      const persistedScore = scoresByDocument.get(ranking.document_id)
      if (!persistedScore) throw new Error(`Score data missing for ${ranking.document_id}.`)
      return {
        id: ranking.document_id,
        documentId: ranking.document_id,
        name: ranking.candidate_name || 'Candidate',
        email: ranking.email || '',
        resumeFile: state.upload.resumes.find((r: any) => r.id === ranking.document_id)?.name || ranking.document_id,
        overallScore: ranking.final_score,
        rank: ranking.rank_position,
        percentile: ranking.percentile,
        confidence: ranking.confidence,
        recommendation: ranking.recommendation,
        isKnockedOut: ranking.is_knocked_out,
        knockoutReason: ranking.knockout_reason,
        rejectionReason: ranking.is_knocked_out ? 'knockout' : ranking.recommendation === 'REJECT' ? 'below_recommendation_threshold' : undefined,
        status: recommendationToStatus(ranking.recommendation, ranking.is_knocked_out),
        extractedFields: [],
        scores: components.map(([key, label]) => {
          const detail = persistedScore.component_scores[key]
          const explanation = detail.explanation
          const isApplicable = !(/\(N\/A\)/i.test(explanation) || (key === 'experience' && /against 0 required months/i.test(explanation)))
          return {
            criterionId: key, label,
            score: detail.score,
            weight: (persistedScore.effective_weights && persistedScore.effective_weights[key] !== undefined) ? persistedScore.effective_weights[key] : config.weights[key],
            weightedScore: persistedScore.weighted_scores[key],
            isApplicable, explanation,
          }
        }),
        matchVerdicts: persistedScore.match_verdicts || [],
        passingScore: persistedScore.passing_score ?? config.passing_score,
        effectiveWeights: persistedScore.effective_weights,
        scoreBreakdown: persistedScore.score_breakdown || [],
        scoredAt: new Date(ranking.created_at),
      }
    })
  }, [state.upload.resumes])

  const [fetchError, setFetchError] = useState<string | null>(null)

  // Load rankings from backend
  useEffect(() => {
    if (!state.projectId) { setRankingsLoading(false); return }
    let active = true
    setRankingsLoading(true)
    const dummyConfig: WeightConfig = { id: '', project_id: state.projectId, weights: { skills: 50, experience: 0, projects: 50, education: 0, certifications: 0, languages: 0 }, passing_score: 60, min_experience_years: 0, required_degree: null, required_certifications: [], mandatory_skills: [], preferred_skills: [], knockout_rules: [], custom_keywords: [], version: 1, created_at: '', updated_at: '' }
    Promise.all([api.getRankings(state.projectId, { page_size: 100 }), api.getProjectScores(state.projectId)])
      .then(([response, scores]) => {
        if (active) {
          dispatch({ type: 'SET_RANKED_CANDIDATES', payload: mapRankings(response.items, scores, dummyConfig) })
          setFetchError(null)
        }
      })
      .catch((err) => {
        if (!active) return
        setFetchError(err instanceof Error ? err.message : 'Failed to fetch candidate rankings.')
      })
      .finally(() => { if (active) setRankingsLoading(false) })
    return () => { active = false }
  }, [dispatch, mapRankings, state.projectId])

  // Derived data
  const filtered = candidates
    .filter((c) => {
      const q = search.toLowerCase()
      const matchSearch = c.name.toLowerCase().includes(q) || c.email.toLowerCase().includes(q)
      const matchStatus = filterStatus === 'all' || c.status === filterStatus
      return matchSearch && matchStatus
    })
    .sort((a, b) => sortBy === 'rank' ? a.rank - b.rank : b.overallScore - a.overallScore)

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
        onClose={() => setSelectedCandidate(null)}
      />

      <motion.div variants={container} initial="hidden" animate="show" className="max-w-6xl mx-auto space-y-5 pb-8">

        {/* ── Page Header ── */}
        <motion.div variants={fadeUp} className="flex items-start justify-between">
          <div>
            <h1 className="text-[28px] font-bold tracking-tight text-slate-900 mb-1">Candidate Rankings</h1>
            <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
              Candidates have been evaluated against the job requirements and ranked by relevance. Click any candidate to view the detailed match explanation.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <select
              className="text-[12px] border border-slate-200 rounded-lg px-3 py-2 text-slate-600 outline-none bg-white font-medium hover:border-blue-300 transition-colors"
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
              <option value="" disabled>Export...</option>
              <option value="csv">Export CSV</option>
              <option value="excel">Export Excel</option>
              <option value="json">Export JSON</option>
            </select>
            <motion.button
              onClick={handleGoToShortlist}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-xl text-[12px] font-bold hover:bg-blue-700 transition-colors shadow-sm"
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
            >
              <UserCheck size={14} />
              Go to Shortlist
              <ArrowRight size={13} />
            </motion.button>
          </div>
        </motion.div>

        {/* ── KPI Cards ── */}
        <motion.div variants={fadeUp} className="grid grid-cols-4 gap-3">
          {[
            { icon: Users,       label: 'Total Candidates',     value: candidates.length, color: 'text-blue-600',   bg: 'bg-blue-50 border-blue-100'   },
            { icon: CheckCircle2,label: 'Shortlisted',          value: shortlisted,       color: 'text-emerald-600', bg: 'bg-emerald-50 border-emerald-100' },
            { icon: HelpCircle,  label: 'Needs Review',         value: needsReview,       color: 'text-amber-600',   bg: 'bg-amber-50 border-amber-100'   },
            { icon: Trophy,      label: 'Avg Match Score',      value: `${avgScore}%`,    color: 'text-blue-600',    bg: 'bg-white border-slate-200'      },
          ].map((kpi) => {
            const Icon = kpi.icon
            return (
              <motion.div key={kpi.label} className={`rounded-2xl border p-5 ${kpi.bg}`} whileHover={{ y: -2 }}>
                <div className="flex items-center gap-2 mb-2">
                  <Icon size={14} className={kpi.color} />
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">{kpi.label}</p>
                </div>
                <motion.p key={String(kpi.value)} className={`text-[26px] font-extrabold ${kpi.color}`} initial={{ scale: 0.85 }} animate={{ scale: 1 }}>
                  {kpi.value}
                </motion.p>
              </motion.div>
            )
          })}
        </motion.div>

        {/* ── Candidate Table ── */}
        <motion.div variants={fadeUp} className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">

          {/* Toolbar */}
          <div className="flex items-center gap-3 px-5 py-3.5 border-b border-slate-100 bg-slate-50/40">
            <div className="flex items-center gap-2 flex-1 bg-white rounded-xl px-3 py-2 border border-slate-200">
              <Search size={13} className="text-slate-400 flex-shrink-0" />
              <input
                type="text"
                placeholder="Search candidates by name or email…"
                className="bg-transparent outline-none text-[12px] text-slate-600 flex-1 placeholder-slate-300"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <select
              className="text-[12px] border border-slate-200 rounded-xl px-3 py-2 text-slate-600 outline-none bg-white"
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as ScreeningStatus | 'all')}
            >
              <option value="all">All Candidates</option>
              <option value="screened">Shortlisted</option>
              <option value="pending">Needs Review</option>
              <option value="rejected">Not Relevant</option>
            </select>

            <button
              onClick={() => setSortBy((s) => (s === 'rank' ? 'score' : 'rank'))}
              className="flex items-center gap-1.5 text-[12px] text-slate-500 hover:text-blue-600 px-3 py-2 rounded-xl hover:bg-blue-50 border border-slate-200 transition-colors font-medium"
            >
              <Filter size={12} />
              Sort: {sortBy === 'rank' ? 'By Rank' : 'By Score'}
            </button>

            <div className="text-[11px] text-slate-400 font-medium px-2">
              {filtered.length} of {candidates.length} candidates
            </div>
          </div>

          {/* Error notification strip */}
          {fetchError && (
            <div className="flex items-center gap-2 px-5 py-3 bg-red-50 border-b border-red-200 text-red-700 text-xs font-semibold">
              <AlertCircle size={14} />
              <span>{fetchError}</span>
            </div>
          )}

          {/* Hint strip */}
          <div className="flex items-center gap-2 px-5 py-2.5 bg-blue-50/40 border-b border-blue-100/60">
            <Sparkles size={12} className="text-blue-400" />
            <p className="text-[11px] text-blue-600 font-medium">
              Click any candidate row to view the full match explanation and score breakdown.
            </p>
          </div>

          {/* Table */}
          {rankingsLoading ? (
            <div className="py-16 text-center text-slate-400">
              <motion.div className="w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full mx-auto mb-3"
                animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }} />
              <p className="text-[13px]">Loading candidate rankings…</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-slate-100 text-left">
                    <th className="px-5 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider w-14">Rank</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider">Candidate</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center w-28">Final Score</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider">Recommendation</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center">Skill Match</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center">AI Relevance</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center w-24">Action</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center w-20">Explain</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  <AnimatePresence>
                    {filtered.map((candidate, idx) => {
                      const rec = getRecommendationConfig(candidate)
                      const skillScoreObj = candidate.scores.find((s) => s.criterionId === 'skills')
                      const skillScore50 = Math.round(((skillScoreObj?.score ?? 0) / 100) * 50)

                      // Calculate AI relevance (50 marks max) from non-skill categories
                      const nonSkillScores = candidate.scores.filter((s) => s.criterionId !== 'skills')
                      const avgNonSkill = nonSkillScores.length
                        ? nonSkillScores.reduce((acc, curr) => acc + curr.score, 0) / nonSkillScores.length
                        : candidate.overallScore
                      const aiRelevance50 = Math.round((avgNonSkill / 100) * 50)

                      return (
                        <motion.tr
                          key={candidate.id}
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0 }}
                          transition={{ delay: idx * 0.04 }}
                          className="hover:bg-blue-50/30 cursor-pointer transition-colors group"
                          onClick={() => setSelectedCandidate(candidate)}
                        >
                          {/* Rank */}
                          <td className="px-5 py-3.5">
                            <div className="flex items-center gap-1">
                              {candidate.rank <= 3 && (
                                <span className="text-[15px]">
                                  {candidate.rank === 1 ? '🥇' : candidate.rank === 2 ? '🥈' : '🥉'}
                                </span>
                              )}
                              <span className="text-[13px] font-bold text-slate-400">#{candidate.rank}</span>
                            </div>
                          </td>

                          {/* Candidate */}
                          <td className="px-4 py-3.5">
                            <div className="flex items-center gap-2.5">
                              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white font-bold text-[10px] flex-shrink-0">
                                {candidate.name.split(' ').map((n) => n[0]).join('').slice(0, 2)}
                              </div>
                              <div>
                                <p className="text-[13px] font-semibold text-slate-800 leading-tight">{candidate.name}</p>
                                <div className="flex items-center gap-1 text-[10px] text-slate-400 mt-0.5">
                                  <Mail size={9} />
                                  <span>{candidate.email}</span>
                                </div>
                                {candidate.currentTitle && (
                                  <div className="flex items-center gap-1 text-[10px] text-slate-400">
                                    <Briefcase size={9} />
                                    <span>{candidate.currentTitle}</span>
                                  </div>
                                )}
                              </div>
                            </div>
                          </td>

                          {/* Final Score */}
                          <td className="px-4 py-3.5 text-center">
                            <span className={`inline-block px-2.5 py-1 rounded-lg text-[13px] font-extrabold border ${getScoreBg(candidate.overallScore)} ${getScoreColor(candidate.overallScore)}`}>
                              {candidate.overallScore} / 100
                            </span>
                          </td>

                          {/* Recommendation */}
                          <td className="px-4 py-3.5">
                            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-bold ${rec.cls}`}>
                              <rec.Icon size={11} className={rec.iconColor} />
                              {rec.label}
                            </span>
                          </td>

                          {/* Skill Match Score (50 Marks) */}
                          <td className="px-4 py-3.5 text-center">
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-blue-50 text-blue-700 text-[11.5px] font-extrabold border border-blue-100">
                              {skillScore50} / 50
                            </span>
                          </td>

                          {/* AI Relevance Score (50 Marks) */}
                          <td className="px-4 py-3.5 text-center">
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-700 text-[11.5px] font-extrabold border border-emerald-100">
                              {aiRelevance50} / 50
                            </span>
                          </td>

                          {/* Action (status change) */}
                          <td className="px-4 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
                            <select
                              className="text-[11px] border border-slate-200 rounded-lg px-2 py-1.5 text-slate-600 outline-none bg-white hover:border-blue-300 transition-colors font-medium"
                              value={candidate.status}
                              onChange={(e) => {
                                e.stopPropagation()
                                updateStatus(candidate.id, e.target.value as ScreeningStatus)
                              }}
                            >
                              <option value="screened">Shortlist</option>
                              <option value="pending">Review</option>
                              <option value="rejected">Reject</option>
                            </select>
                          </td>

                          {/* Explain */}
                          <td className="px-4 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
                            <motion.button
                              className="inline-flex items-center gap-1 text-[11px] font-semibold text-blue-600 hover:text-blue-700 px-2.5 py-1.5 rounded-lg hover:bg-blue-50 border border-blue-100 transition-colors"
                              onClick={(e) => { e.stopPropagation(); setSelectedCandidate(candidate) }}
                              whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }}
                            >
                              <Sparkles size={11} />
                              Explain
                            </motion.button>
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
                  <p className="text-[13px]">
                    {search || filterStatus !== 'all' ? 'No candidates match your filter.' : 'No candidates have been ranked yet.'}
                  </p>
                  {(search || filterStatus !== 'all') && (
                    <button onClick={() => { setSearch(''); setFilterStatus('all') }} className="mt-2 text-[12px] text-blue-500 hover:underline">
                      Clear filters
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Table footer: summary */}
          {candidates.length > 0 && (
            <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/40 flex items-center justify-between text-[11px] text-slate-500">
              <span>
                {shortlisted} shortlisted · {needsReview} pending review · {rejected} not relevant
              </span>
              <span>
                {candidates.length} total candidates evaluated
              </span>
            </div>
          )}
        </motion.div>

        {/* ── CTA Footer ── */}
        <motion.div variants={fadeUp} className="flex items-center justify-between">
          <p className="text-[12px] text-slate-400">
            Review candidates, then proceed to the Shortlist to confirm your selections.
          </p>
          <motion.button
            onClick={handleGoToShortlist}
            className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 text-white rounded-xl text-[12px] font-bold hover:bg-blue-700 transition-colors shadow-sm"
            whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
          >
            <UserCheck size={14} />
            Proceed to Shortlist
            <ChevronRight size={13} />
          </motion.button>
        </motion.div>

      </motion.div>
    </>
  )
}
