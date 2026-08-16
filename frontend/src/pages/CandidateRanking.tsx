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

// ─── Recommendation / Screening helpers ─────────────────────────────────────────
function getScreeningStatusConfig(isScreened: boolean): {
  label: string
  cls: string
  iconColor: string
  Icon: typeof CheckCircle2
} {
  if (isScreened) {
    return {
      label: 'SCREENED',
      cls: 'bg-emerald-50 text-emerald-700 border border-emerald-200',
      iconColor: 'text-emerald-500',
      Icon: CheckCircle2,
    }
  }
  return {
    label: 'NOT SCREENED',
    cls: 'bg-slate-100 text-slate-600 border border-slate-200',
    iconColor: 'text-slate-400',
    Icon: ThumbsDown,
  }
}

function getScoreColor(score: number, threshold: number) {
  if (score >= threshold) return 'text-emerald-600'
  return 'text-slate-600'
}

function getScoreBg(score: number, threshold: number) {
  if (score >= threshold) return 'bg-emerald-50 border-emerald-200'
  return 'bg-slate-50 border-slate-200'
}

// ─── Explanation Drawer ───────────────────────────────────────────────────────
interface ExplanationDrawerProps {
  candidate: Candidate | null
  projectId: string | null
  jdDocumentId: string | null
  screeningThreshold: number
  onClose: () => void
}

function ExplanationDrawer({ candidate, projectId, jdDocumentId, screeningThreshold, onClose }: ExplanationDrawerProps) {
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

  const aiSummaryText = insights?.summary || candidate?.aiExplanation || 'Match evaluation derived from normalized candidate resume features against job requirements.'
  const displayStrengths = insights?.strengths?.length ? insights.strengths : candidate?.keyStrengths || []
  const displayWeaknesses = insights?.weaknesses?.length ? insights.weaknesses : candidate?.keyWeaknesses || []

  const score = candidate?.overallScore ?? 0
  const isScreened = score >= screeningThreshold
  const statusConfig = getScreeningStatusConfig(isScreened)

  const filteredStrengths = displayStrengths.filter((s) => !s.toLowerCase().includes('education'))
  const filteredWeaknesses = displayWeaknesses.filter((w) => !w.toLowerCase().includes('education'))

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
                <div className={`px-3 py-1.5 rounded-xl text-[13px] font-extrabold border ${getScoreBg(score, screeningThreshold)} ${getScoreColor(score, screeningThreshold)}`}>
                  {score.toFixed(1)} / 100
                </div>
                <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors">
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Status banner */}
            <div className={`px-6 py-3 flex items-center gap-2.5 border-b text-[12px] font-bold ${statusConfig.cls}`}>
              <statusConfig.Icon size={14} className={statusConfig.iconColor} />
              <span>Status: {statusConfig.label}</span>
              <span className="ml-auto font-normal text-[11px] opacity-70">Rank #{candidate.rank} (Threshold: {screeningThreshold})</span>
            </div>

            {/* Scrollable content */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
              {/* Candidate profile */}
              {loadingProfile && <div className="rounded-xl border border-slate-200 p-4 text-[12px] text-slate-500">Loading candidate profile…</div>}
              {profileError && <div className="rounded-xl border border-amber-100 bg-amber-50 p-4 text-[12px] text-amber-700">Profile unavailable: {profileError}</div>}
              {resumeProfile && <CandidateProfile normalized={resumeProfile.normalized} extracted={resumeProfile.extracted} document={resumeProfile.document} />}

              {/* Experience Level Comparison Card */}
              <div className="grid grid-cols-2 gap-3 p-3.5 rounded-xl bg-slate-900 text-white text-[12px]">
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-400">JD Required Level</p>
                  <p className="text-[14px] font-extrabold text-blue-400">
                    {candidate.effectiveWeights && candidate.effectiveWeights.experience === 0 ? 'Fresher' : 'Experienced'}
                  </p>
                  <p className="text-[10px] text-slate-400 mt-0.5">Controls scoring formula</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-400">Candidate Level</p>
                  <p className="text-[14px] font-extrabold text-emerald-400">
                    {resumeProfile?.normalized?.candidate_level || 'Fresher'} ({resumeProfile?.normalized?.total_experience_months || 0} mos)
                  </p>
                  <p className="text-[10px] text-slate-400 mt-0.5">Resume profile experience</p>
                </div>
              </div>

              {/* Match Evaluation Overview */}
              <div className="rounded-xl bg-gradient-to-br from-blue-50 to-slate-50 border border-blue-100 p-5">
                <div className="flex items-center gap-2 mb-3">
                  <Sparkles size={14} className="text-blue-500" />
                  <p className="text-[11px] font-bold text-blue-600 uppercase tracking-widest">
                    Match Explanation {loadingInsights ? '(Loading...)' : ''}
                  </p>
                </div>
                <p className="text-[13px] text-slate-700 leading-relaxed">{aiSummaryText}</p>
              </div>

              {/* Component Score Breakdown */}
              {candidate.scores && candidate.scores.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 mb-2">
                    <Sparkles size={13} className="text-blue-500" />
                    <p className="text-[11px] font-bold text-blue-600 uppercase tracking-widest">Component Score Breakdown</p>
                  </div>
                  <div className="grid grid-cols-1 gap-2">
                    {candidate.scores.map((sc) => {
                      const contribution = sc.weightedScore ?? ((sc.score * sc.weight) / 100)
                      return (
                        <div key={sc.criterionId} className="p-3 rounded-xl border border-slate-200 bg-slate-50/60 text-[12px] space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-slate-800">{sc.label}</span>
                            <span className={`font-extrabold text-[13.5px] ${sc.score >= 75 ? 'text-emerald-600' : sc.score >= 50 ? 'text-amber-600' : 'text-slate-600'}`}>
                              Score: {sc.score.toFixed(1)}%
                            </span>
                          </div>
                          <div className="flex items-center justify-between text-[11px] text-slate-500 font-medium pt-0.5 border-t border-slate-100">
                            <span>Weight: {sc.weight}%</span>
                            <span>Contribution: {contribution.toFixed(2)}</span>
                            {!sc.isApplicable && <span className="text-slate-400 font-normal">Applicable: false</span>}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Key matched requirements */}
              {filteredStrengths.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <TrendingUp size={13} className="text-emerald-500" />
                    <p className="text-[11px] font-bold text-emerald-600 uppercase tracking-widest">Key Matched Strengths</p>
                  </div>
                  <ul className="space-y-1.5">
                    {filteredStrengths.map((s, i) => (
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
              {filteredWeaknesses.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <AlertCircle size={13} className="text-amber-500" />
                    <p className="text-[11px] font-bold text-amber-600 uppercase tracking-widest">Areas Requiring Review</p>
                  </div>
                  <ul className="space-y-1.5">
                    {filteredWeaknesses.map((w, i) => (
                      <motion.li key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.15 + i * 0.05 }}
                        className="flex items-start gap-2 text-[12.5px] text-slate-600">
                        <AlertCircle size={13} className="text-amber-400 flex-shrink-0 mt-0.5" />
                        {w}
                      </motion.li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Final Score Details */}
              <div className="rounded-xl bg-slate-900 text-white p-5 space-y-3 shadow-sm">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-[12px] font-bold text-slate-300">Final Match Score</p>
                    <p className="text-[10px] text-slate-400">Step 4 Weighted Score (0–100)</p>
                  </div>
                  <p className="text-[28px] font-extrabold text-white">
                    {score.toFixed(1)}
                    <span className="text-[13px] font-normal text-slate-400 ml-1">/ 100</span>
                  </p>
                </div>
                <div className="pt-3 border-t border-slate-800 flex items-center justify-between text-[11px]">
                  <span className="text-slate-400">Configured Threshold: <strong className="text-white">{screeningThreshold}</strong></span>
                  <span className={`px-2 py-0.5 rounded font-extrabold ${isScreened ? 'bg-emerald-950 text-emerald-400' : 'bg-slate-800 text-slate-400'}`}>
                    {isScreened ? 'SCREENED' : 'NOT SCREENED'}
                  </span>
                </div>
              </div>
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
  const [screeningThreshold, setScreeningThreshold] = useState<number>(70)
  const [filterStatus, setFilterStatus] = useState<'all' | 'screened' | 'not_screened'>('all')
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
      ['projects', 'Responsibilities / Projects'],
      ['certifications', 'Preferred Skills'],
      ['languages', 'Job Title / Role Relevance'],
      ['experience', 'Relevant Experience'],
    ] as const
    return rankings.map((ranking) => {
      const persistedScore = scoresByDocument.get(ranking.document_id)
      const authoritativeScore = (persistedScore?.final_score !== undefined && persistedScore.final_score !== null)
        ? Number(persistedScore.final_score)
        : (ranking.final_score !== undefined && ranking.final_score !== null ? Number(ranking.final_score) : 0)

      return {
        id: ranking.document_id,
        documentId: ranking.document_id,
        name: ranking.candidate_name || 'Candidate',
        email: ranking.email || '',
        resumeFile: state.upload.resumes.find((r: any) => r.id === ranking.document_id)?.name || ranking.document_id,
        overallScore: authoritativeScore,
        rank: ranking.rank_position,
        percentile: ranking.percentile,
        confidence: ranking.confidence,
        recommendation: ranking.recommendation,
        isKnockedOut: ranking.is_knocked_out,
        knockoutReason: ranking.knockout_reason,
        status: 'pending',
        extractedFields: [],
        scores: persistedScore ? components.map(([key, label]) => {
          const detail = persistedScore.component_scores[key] || { score: 0, matched_items: [], missing_items: [], explanation: '' }
          const weight = (persistedScore.effective_weights && persistedScore.effective_weights[key] !== undefined)
            ? Number(persistedScore.effective_weights[key])
            : Number(config.weights[key] ?? 0)
          const weightedScore = (persistedScore.weighted_scores && persistedScore.weighted_scores[key] !== undefined)
            ? Number(persistedScore.weighted_scores[key])
            : Number(((detail.score * weight) / 100).toFixed(2))
          const isApplicable = weight > 0
          return {
            criterionId: key, label,
            score: Number(detail.score ?? 0),
            weight,
            weightedScore,
            isApplicable,
            explanation: detail.explanation || '',
          }
        }) : [],
        matchVerdicts: persistedScore?.match_verdicts || [],
        passingScore: persistedScore?.passing_score ?? config.passing_score,
        effectiveWeights: persistedScore?.effective_weights,
        scoreBreakdown: persistedScore?.score_breakdown || [],
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
          const freshMapped = mapRankings(response.items, scores, dummyConfig)
          dispatch({ type: 'SET_RANKED_CANDIDATES', payload: freshMapped })
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

  // Derived filtered data
  const filtered = candidates
    .filter((c) => {
      const q = search.toLowerCase()
      const matchSearch = c.name.toLowerCase().includes(q) || c.email.toLowerCase().includes(q)
      const isScreened = (c.overallScore ?? 0) >= screeningThreshold
      const matchStatus =
        filterStatus === 'all' ||
        (filterStatus === 'screened' && isScreened) ||
        (filterStatus === 'not_screened' && !isScreened)
      return matchSearch && matchStatus
    })
    .sort((a, b) => (sortBy === 'rank' ? a.rank - b.rank : (b.overallScore ?? 0) - (a.overallScore ?? 0)))

  const totalScreened = candidates.filter((c) => (c.overallScore ?? 0) >= screeningThreshold).length
  const totalNotScreened = candidates.length - totalScreened

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
        screeningThreshold={screeningThreshold}
        onClose={() => setSelectedCandidate(null)}
      />

      <motion.div variants={container} initial="hidden" animate="show" className="max-w-6xl mx-auto space-y-5 pb-8">

        {/* ── Page Header ── */}
        <motion.div variants={fadeUp} className="flex items-start justify-between">
          <div>
            <h1 className="text-[28px] font-bold tracking-tight text-slate-900 mb-1">Candidate Rankings</h1>
            <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
              Candidates are evaluated against job requirements and ranked by Final Match Score. Configure your screening threshold to view screened candidates.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <motion.button
              onClick={handleGoToShortlist}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-xl text-[12px] font-bold hover:bg-blue-700 transition-colors shadow-sm"
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
            >
              <UserCheck size={14} />
              View Shortlist
              <ArrowRight size={13} />
            </motion.button>
          </div>
        </motion.div>

        {/* ── Candidate Table Container ── */}
        <motion.div variants={fadeUp} className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">

          {/* Toolbar */}
          <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 border-b border-slate-100 bg-slate-50/40">
            {/* Search */}
            <div className="flex items-center gap-2 flex-1 min-w-[200px] bg-white rounded-xl px-3 py-2 border border-slate-200">
              <Search size={13} className="text-slate-400 flex-shrink-0" />
              <input
                type="text"
                placeholder="Search candidates by name or email…"
                className="bg-transparent outline-none text-[12px] text-slate-600 flex-1 placeholder-slate-300"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            {/* Threshold Control */}
            <div className="flex items-center gap-2 bg-white rounded-xl px-3 py-1.5 border border-slate-200">
              <span className="text-[11px] font-bold text-slate-600">Threshold:</span>
              <input
                type="number"
                min="0"
                max="100"
                value={screeningThreshold}
                onChange={(e) => {
                  const val = Math.min(100, Math.max(0, Number(e.target.value) || 0))
                  setScreeningThreshold(val)
                }}
                className="w-14 text-center font-extrabold text-[12px] text-blue-700 bg-blue-50 border border-blue-200 rounded-lg py-0.5 outline-none"
              />
              <span className="text-[11px] text-slate-400 font-medium">/ 100</span>
            </div>

            {/* Status Filter */}
            <select
              className="text-[12px] border border-slate-200 rounded-xl px-3 py-2 text-slate-600 outline-none bg-white font-medium"
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as 'all' | 'screened' | 'not_screened')}
            >
              <option value="all">All Candidates</option>
              <option value="screened">SCREENED (≥ {screeningThreshold})</option>
              <option value="not_screened">NOT SCREENED (&lt; {screeningThreshold})</option>
            </select>

            {/* Sort Toggle */}
            <button
              onClick={() => setSortBy((s) => (s === 'rank' ? 'score' : 'rank'))}
              className="flex items-center gap-1.5 text-[12px] text-slate-500 hover:text-blue-600 px-3 py-2 rounded-xl hover:bg-blue-50 border border-slate-200 transition-colors font-medium"
            >
              <Filter size={12} />
              Sort: {sortBy === 'rank' ? 'By Rank' : 'By Score'}
            </button>

            <div className="text-[11px] text-slate-400 font-medium px-1">
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
                    <th className="px-5 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider w-16">Rank</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider">Candidate</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center w-36">Final Match Score</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center w-36">Screening Status</th>
                    <th className="px-4 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center w-24">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  <AnimatePresence>
                    {filtered.map((candidate, idx) => {
                      const score = candidate.overallScore ?? 0
                      const isScreened = score >= screeningThreshold
                      const statusConfig = getScreeningStatusConfig(isScreened)

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

                          {/* Final Match Score */}
                          <td className="px-4 py-3.5 text-center">
                            <span className={`inline-block px-3 py-1.5 rounded-xl text-[13.5px] font-extrabold border ${getScoreBg(score, screeningThreshold)} ${getScoreColor(score, screeningThreshold)}`}>
                              {score.toFixed(1)} / 100
                            </span>
                          </td>

                          {/* Screening Status Badge */}
                          <td className="px-4 py-3.5 text-center">
                            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-xl text-[11px] font-extrabold ${statusConfig.cls}`}>
                              <statusConfig.Icon size={12} className={statusConfig.iconColor} />
                              {statusConfig.label}
                            </span>
                          </td>

                          {/* Action / Explain */}
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

          {/* Summary footer */}
          {candidates.length > 0 && (
            <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/40 flex items-center justify-between text-[11px] text-slate-500 font-medium">
              <span>
                <strong className="text-emerald-700">{totalScreened} SCREENED</strong> (Score ≥ {screeningThreshold}) · <strong className="text-slate-600">{totalNotScreened} NOT SCREENED</strong>
              </span>
              <span>
                {candidates.length} total candidates ranked by Final Match Score
              </span>
            </div>
          )}
        </motion.div>

      </motion.div>
    </>
  )
}
