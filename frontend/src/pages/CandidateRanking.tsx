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



              {/* Backend Component Scoring Breakdown (100% Model) */}
              <div className="space-y-2.5">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">
                    Component Scoring Breakdown
                  </p>
                </div>
                
                {(() => {
                  const getDetail = (key: string, fallbackWeight: number) => {
                    const scoreObj = candidate.scores.find((s) => s.criterionId === key)
                    const bItem = candidate.scoreBreakdown?.find((b) => b.category === key || (key === 'skills' && b.category === 'required_skills'))
                    const scoreVal = scoreObj?.score ?? bItem?.component_score ?? 0
                    const weightVal = (scoreObj?.weight && scoreObj.weight > 0) ? scoreObj.weight : (bItem?.effective_weight ?? fallbackWeight)
                    const contributionVal = scoreObj?.weightedScore ?? bItem?.contribution ?? ((scoreVal * weightVal) / 100)
                    return { scoreVal, weightVal, contributionVal }
                  }

                  const componentsList = [
                    { key: 'skills', label: 'Required Skills', defaultWeight: 30 },
                    { key: 'responsibilities', label: 'Responsibilities', defaultWeight: 25 },
                    { key: 'projects', label: 'Projects', defaultWeight: 25 },
                    { key: 'preferred_skills', label: 'Preferred Skills', defaultWeight: 15 },
                    { key: 'certifications', label: 'Certifications', defaultWeight: 5 },
                  ]

                  return (
                    <div className="space-y-2.5">
                      <div className="grid grid-cols-2 gap-2.5">
                        {componentsList.map((c) => {
                          const { scoreVal, weightVal, contributionVal } = getDetail(c.key, c.defaultWeight)
                          const roundedScore = Math.round(scoreVal)
                          const roundedContrib = Number(contributionVal).toFixed(1)

                          return (
                            <div
                              key={c.key}
                              className="bg-slate-50/80 border border-slate-100 rounded-xl p-2.5 space-y-1.5 hover:border-blue-200 transition-colors"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span className="text-[11px] text-slate-700 font-bold truncate">
                                  {c.label}
                                </span>
                                <span className="text-[12px] font-extrabold text-slate-800 shrink-0">
                                  {roundedScore}%
                                </span>
                              </div>
                              <div className="w-full h-1.5 bg-slate-200/80 rounded-full overflow-hidden">
                                <motion.div
                                  className={`h-full rounded-full ${
                                    roundedScore >= 50 ? 'bg-emerald-500' : 'bg-amber-500'
                                  }`}
                                  initial={{ width: 0 }}
                                  animate={{ width: `${Math.min(100, Math.max(0, roundedScore))}%` }}
                                  transition={{ duration: 0.5 }}
                                />
                              </div>
                              <div className="flex items-center justify-between text-[9.5px] text-slate-500">
                                <span>Weight: {Math.round(weightVal)}%</span>
                                <span>Contr: {roundedContrib}%</span>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })()}
              </div>

              {/* Requirement-level AI verdicts and reasoning */}
              {(candidate.matchVerdicts?.length ?? 0) > 0 && (
                <div className="space-y-2.5">
                  <p className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">AI Requirement Evaluation & Reasoning</p>
                  <div className="space-y-2">
                    {candidate.matchVerdicts!.map((verdict) => {
                      const isMatched = verdict.status === 'MATCHED'
                      const isNoMatch = verdict.status === 'NO_MATCH'
                      const reqText = (verdict as any).requirement_text || requirementLabels.get(verdict.requirement_id) || verdict.requirement_id
                      const method = verdict.method || ''
                      const isLlm = typeof method === 'string' && method.toLowerCase().includes('llm')
                      
                      return (
                        <div
                          key={verdict.requirement_id}
                          className={`rounded-xl border p-3.5 space-y-1.5 transition-all ${
                            isMatched
                              ? 'bg-emerald-50/40 border-emerald-100'
                              : isNoMatch
                              ? 'bg-rose-50/30 border-rose-100'
                              : 'bg-slate-50 border-slate-100'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <p className="text-[12px] font-semibold text-slate-800 leading-snug">{reqText}</p>
                            <span
                              className={`shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-md uppercase tracking-wider ${
                                isMatched
                                  ? 'bg-emerald-100 text-emerald-800'
                                  : isNoMatch
                                  ? 'bg-rose-100 text-rose-800'
                                  : 'bg-slate-200 text-slate-700'
                              }`}
                            >
                              {isMatched ? (isLlm ? 'AI Confirmed' : 'Matched') : isNoMatch ? (isLlm ? 'AI Unmet' : 'Unmet') : 'Unresolved'}
                            </span>
                          </div>
                          {verdict.reasoning && (
                            <p className="text-[11.5px] text-slate-600 leading-relaxed bg-white/70 rounded-lg p-2 border border-slate-100">
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
      ['skills', 'Required Skills'],
      ['responsibilities', 'Responsibilities'],
      ['projects', 'Projects'],
      ['preferred_skills', 'Preferred Skills'],
      ['experience', 'Experience'],
      ['certifications', 'Certifications'],
      ['education', 'Education'],
      ['languages', 'Languages'],
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
        scores: components
          .map(([key, label]) => {
            const detail = (persistedScore.component_scores as any)?.[key]
            if (!detail) return null
            const explanation = detail.explanation || ''
            const isApplicable = !(/\(N\/A\)/i.test(explanation) || (key === 'experience' && /against 0 required months/i.test(explanation)))
            const weightKey = key === 'skills' ? 'required_skills' : key
            const effectiveWeight = (persistedScore.effective_weights && (persistedScore.effective_weights[weightKey] ?? persistedScore.effective_weights[key])) ?? (config.weights as any)?.[key] ?? (key === 'skills' ? 30 : key === 'responsibilities' ? 25 : key === 'projects' ? 20 : key === 'preferred_skills' ? 15 : key === 'experience' ? 5 : key === 'certifications' ? 3 : key === 'education' ? 2 : 0)
            const weightedScore = (persistedScore.weighted_scores as any)?.[key] ?? (detail.score * effectiveWeight / 100)
            return {
              criterionId: key,
              label,
              score: detail.score,
              weight: effectiveWeight,
              weightedScore,
              isApplicable,
              explanation,
            }
          })
          .filter(Boolean) as any[],
        matchVerdicts: persistedScore.match_verdicts || (persistedScore as any).matchVerdicts || [],
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

    const loadData = async () => {
      try {
        let [response, scores] = await Promise.all([
          api.getRankings(state.projectId!, { page_size: 100 }),
          api.getProjectScores(state.projectId!),
        ])

        if ((!response.items || response.items.length === 0) && active) {
          try {
            await api.scoreProject(state.projectId!)
            await api.rankProject(state.projectId!)
            ;[response, scores] = await Promise.all([
              api.getRankings(state.projectId!, { page_size: 100 }),
              api.getProjectScores(state.projectId!),
            ])
          } catch {
            // Ignore if project has no candidates or missing JD
          }
        }

        if (active) {
          const freshMapped = mapRankings(response.items || [], scores || [], dummyConfig)
          const existingStatusMap = new Map(state.candidates.map((c) => [c.id, c.status]))
          const merged = freshMapped.map((c) => {
            const overrideStatus = existingStatusMap.get(c.id)
            return overrideStatus !== undefined ? { ...c, status: overrideStatus } : c
          })
          dispatch({ type: 'SET_RANKED_CANDIDATES', payload: merged })
          setFetchError(null)
        }
      } catch (err) {
        if (active) {
          setFetchError(err instanceof Error ? err.message : 'Failed to fetch candidate rankings.')
        }
      } finally {
        if (active) setRankingsLoading(false)
      }
    }

    loadData()
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
    .sort((a, b) => a.rank - b.rank)

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
              <option value="rejected">Not Relevant</option>
            </select>



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
                    <th className="px-5 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider w-14">S.No</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider">Candidate</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center w-24">Action</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center w-20">Explain</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  <AnimatePresence>
                    {filtered.map((candidate, idx) => {
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
                          {/* S.No */}
                          <td className="px-5 py-3.5">
                            <span className="text-[13px] font-bold text-slate-500">{idx + 1}</span>
                          </td>

                          {/* Candidate */}
                          <td className="px-4 py-3.5">
                            <div className="flex items-center gap-2.5">
                              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white font-bold text-[10px] flex-shrink-0">
                                {candidate.name.split(' ').map((n) => n[0]).join('').slice(0, 2)}
                              </div>
                              <div>
                                <div className="font-bold text-slate-800 text-[13px]">{candidate.name}</div>
                                <div className="text-[11px] text-slate-400 font-normal">{candidate.email}</div>
                              </div>
                            </div>
                          </td>

                          {/* Action (status change) */}
                          <td className="px-4 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
                            <select
                              className={`text-[11px] font-bold border rounded-xl px-2.5 py-1.5 outline-none transition-colors cursor-pointer ${
                                candidate.status === 'screened'
                                  ? 'bg-emerald-50 text-emerald-700 border-emerald-300 hover:bg-emerald-100/70'
                                  : candidate.status === 'pending'
                                  ? 'bg-amber-50 text-amber-700 border-amber-300 hover:bg-amber-100/70'
                                  : 'bg-red-50 text-red-700 border-red-300 hover:bg-red-100/70'
                              }`}
                              value={candidate.status}
                              onChange={(e) => {
                                e.stopPropagation()
                                updateStatus(candidate.id, e.target.value as ScreeningStatus)
                              }}
                            >
                              <option value="screened" className="bg-white text-slate-800 font-medium">Screened</option>
                              <option value="rejected" className="bg-white text-slate-800 font-medium">Reject</option>
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
                {shortlisted} shortlisted · {rejected} not relevant
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
