import React, { useCallback, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Play,
  ListOrdered,
  ArrowRight,
  Search,
  Filter,
  Download,
  ChevronDown,
  ChevronUp,
  Mail,
  Briefcase,
  Users,
  Trophy,
  Star,
  LayoutDashboard,
  X,
  Sparkles,
  CheckCircle2,
  TrendingUp,
  AlertCircle,
} from 'lucide-react'
import AIPipelineRail from '@/components/ui/AIPipelineRail'
import { usePipeline } from '@/store/pipelineStore'
import { Candidate, ScreeningStatus } from '@/types'
import { AI_PIPELINE_STAGES } from '@/constants'
import { useNavigate } from 'react-router-dom'
import {
  api,
  ApiError,
  type CandidateInsights,
  type CandidateRanking as ApiCandidateRanking,
} from '@/api'

// ─── Animation variants ───────────────────────────────────────
const fadeUp = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0 } }
const container = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } }

// ─── Status helpers ────────────────────────────────────────────
const STATUS_STYLES: Record<ScreeningStatus, { cls: string; label: string }> = {
  screened: { cls: 'status-badge status-screened', label: 'Screened' },
  pending:  { cls: 'status-badge status-pending',  label: 'Pending'  },
  rejected: { cls: 'status-badge status-rejected', label: 'Rejected' },
}

function getScoreClass(score: number) {
  if (score >= 80) return 'score-high'
  if (score >= 60) return 'score-med'
  return 'score-low'
}

function recommendationToStatus(
  recommendation: string,
  knockedOut: boolean,
): ScreeningStatus {
  if (knockedOut || recommendation === 'REJECT') return 'rejected'
  if (recommendation === 'SHORTLIST') return 'screened'
  return 'pending'
}

function scoringPrerequisitesMet(state: ReturnType<typeof usePipeline>['state']): string | null {
  if (!state.projectId) return 'No project found. Complete JD upload first.'
  if (!state.jdNormalized) return 'Job description must be normalized before scoring.'
  if (!state.weightConfigSaved) return 'Weight configuration must be saved before scoring.'
  if (state.resumeDocumentIds.length === 0) return 'Upload at least one resume before scoring.'
  const allNormalized = state.resumeDocumentIds.every(
    (id) => state.resumeProcessing[id]?.normalized === true,
  )
  if (!allNormalized) return 'All uploaded resumes must be normalized before scoring.'
  return null
}

// ─── AI Explanation Drawer ────────────────────────────────────
interface ExplanationDrawerProps {
  candidate: Candidate | null
  onClose: () => void
}

function ExplanationDrawer({ candidate, onClose }: ExplanationDrawerProps) {
  const [insights, setInsights] = useState<CandidateInsights | null>(null)
  const [loadingInsights, setLoadingInsights] = useState(false)

  React.useEffect(() => {
    if (!candidate?.id) {
      setInsights(null)
      return
    }
    let isMounted = true
    setLoadingInsights(true)
    api.getInsights(candidate.id)
      .then((res) => {
        if (isMounted) {
          setInsights(res)
          setLoadingInsights(false)
        }
      })
      .catch(() => {
        if (isMounted) setLoadingInsights(false)
      })
    return () => { isMounted = false }
  }, [candidate?.id])

  const aiSummaryText = insights?.summary || candidate?.aiExplanation || 'AI explanation not yet generated. Please run the AI pipeline first.'
  const displayStrengths = insights?.strengths?.length ? insights.strengths : candidate?.keyStrengths || []
  const displayWeaknesses = insights?.weaknesses?.length ? insights.weaknesses : candidate?.keyWeaknesses || []

  return (
    <AnimatePresence>
      {candidate && (
        <>
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            className="fixed inset-0 bg-slate-900/30 backdrop-blur-sm z-40"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />

          {/* Drawer */}
          <motion.div
            key="drawer"
            className="fixed right-0 top-0 bottom-0 w-[480px] bg-white z-50 shadow-2xl flex flex-col"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 280 }}
          >
            {/* Drawer Header */}
            <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-gradient-to-br from-sky-400 to-sky-600 flex items-center justify-center text-white font-bold text-[13px] flex-shrink-0">
                  {candidate.name.split(' ').map((n) => n[0]).join('')}
                </div>
                <div>
                  <p className="text-[15px] font-bold text-slate-800">{candidate.name}</p>
                  <p className="text-[11px] text-slate-400">{candidate.currentTitle}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className={`score-badge ${getScoreClass(candidate.overallScore)}`}>
                  {candidate.overallScore}
                </div>
                <button
                  onClick={onClose}
                  className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Scrollable content */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
              {/* Rank badge */}
              <div className="flex items-center gap-3">
                <span className="text-[20px]">
                  {candidate.rank === 1 ? '🥇' : candidate.rank === 2 ? '🥈' : candidate.rank === 3 ? '🥉' : `#${candidate.rank}`}
                </span>
                <div>
                  <p className="text-[12px] font-semibold text-slate-600">
                    Ranked #{candidate.rank} overall
                  </p>
                  <span className={STATUS_STYLES[candidate.status].cls}>
                    {STATUS_STYLES[candidate.status].label}
                  </span>
                </div>
              </div>

              {/* AI Explanation */}
              <div className="rounded-xl bg-gradient-to-br from-sky-50 to-blue-50 border border-sky-100 p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Sparkles size={14} className="text-sky-500" />
                  <p className="text-[11px] font-bold text-sky-600 uppercase tracking-widest">
                    AI Explanation {loadingInsights ? '(Loading...)' : ''}
                  </p>
                </div>
                <p className="text-[13px] text-slate-600 leading-relaxed">
                  {aiSummaryText}
                </p>
                {insights?.score_explanation && (
                  <p className="mt-2 text-[12px] text-slate-500 italic">
                    {insights.score_explanation}
                  </p>
                )}
              </div>

              {/* Key Strengths */}
              {displayStrengths.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2.5">
                    <TrendingUp size={13} className="text-green-500" />
                    <p className="text-[11px] font-bold text-green-600 uppercase tracking-widest">
                      Key Strengths
                    </p>
                  </div>
                  <ul className="space-y-1.5">
                    {displayStrengths.map((s, i) => (
                      <motion.li
                        key={i}
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.1 + i * 0.06 }}
                        className="flex items-start gap-2 text-[12.5px] text-slate-600"
                      >
                        <CheckCircle2 size={13} className="text-green-500 flex-shrink-0 mt-0.5" />
                        {s}
                      </motion.li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Key Weaknesses */}
              {displayWeaknesses.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2.5">
                    <AlertCircle size={13} className="text-amber-500" />
                    <p className="text-[11px] font-bold text-amber-600 uppercase tracking-widest">
                      Areas to Assess
                    </p>
                  </div>
                  <ul className="space-y-1.5">
                    {displayWeaknesses.map((w, i) => (
                      <motion.li
                        key={i}
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.2 + i * 0.06 }}
                        className="flex items-start gap-2 text-[12.5px] text-slate-600"
                      >
                        <AlertCircle size={13} className="text-amber-400 flex-shrink-0 mt-0.5" />
                        {w}
                      </motion.li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Score breakdown */}
              <div>
                <p className="text-[11px] font-bold text-slate-500 uppercase tracking-widest mb-3">
                  Score Breakdown
                </p>
                <div className="space-y-2.5">
                  {candidate.scores.map((s) => (
                    <div key={s.criterionId}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[12px] text-slate-600 font-medium">{s.label}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] text-slate-400">Weight {s.weight}%</span>
                          <span className="text-[13px] font-bold text-sky-600">{s.score}</span>
                        </div>
                      </div>
                      <div className="progress-track">
                        <motion.div
                          className="progress-fill"
                          initial={{ width: 0 }}
                          animate={{ width: `${s.score}%` }}
                          transition={{ duration: 0.6, delay: 0.2 }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Total score */}
              <div className="rounded-xl bg-slate-50 border border-slate-100 p-4 flex items-center justify-between">
                <p className="text-[13px] font-semibold text-slate-600">Overall Score</p>
                <p className={`text-[28px] font-bold ${getScoreClass(candidate.overallScore).replace('score-', 'text-').replace('high', 'green-600').replace('med', 'amber-500').replace('low', 'red-500')}`}>
                  {candidate.overallScore}
                  <span className="text-[14px] font-normal text-slate-400 ml-1">/ 100</span>
                </p>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

// ─── Main Page ────────────────────────────────────────────────
export default function CandidateRanking() {
  const { state, dispatch, completeAndAdvance } = usePipeline()
  const navigate = useNavigate()

  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState<ScreeningStatus | 'all'>('all')
  const [sortBy, setSortBy] = useState<'rank' | 'score'>('rank')
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null)
  const [rankingsLoading, setRankingsLoading] = useState(true)

  // Derive candidates — prefer scored results; avoid mock fallback after a real score run
  const candidates: Candidate[] = state.candidates

  const mapRankings = useCallback((rankings: ApiCandidateRanking[]): Candidate[] =>
    rankings.map((ranking) => ({
      id: ranking.document_id,
      documentId: ranking.document_id,
      name: ranking.candidate_name || 'Candidate',
      email: ranking.email || '',
      resumeFile: state.upload.resumes.find((resume) => resume.id === ranking.document_id)?.name || ranking.document_id,
      overallScore: Math.round(ranking.final_score),
      rank: ranking.rank_position,
      percentile: ranking.percentile,
      confidence: ranking.confidence,
      recommendation: ranking.recommendation,
      isKnockedOut: ranking.is_knocked_out,
      status: recommendationToStatus(ranking.recommendation, ranking.is_knocked_out),
      extractedFields: [],
      scores: [
        { criterionId: 'skills', label: 'Skills', score: Math.round(ranking.skills_score), weight: 0, weightedScore: 0 },
        { criterionId: 'experience', label: 'Experience', score: Math.round(ranking.experience_score), weight: 0, weightedScore: 0 },
      ],
      scoredAt: new Date(ranking.created_at),
    })), [state.upload.resumes])

  useEffect(() => {
    if (!state.projectId) { setRankingsLoading(false); return }
    let active = true
    setRankingsLoading(true)
    dispatch({ type: 'SET_RANKED_CANDIDATES', payload: [] })
    dispatch({ type: 'SET_SCORING_ERROR', payload: null })
    api.getRankings(state.projectId, { page_size: 100 })
      .then((response) => { if (active) dispatch({ type: 'SET_RANKED_CANDIDATES', payload: mapRankings(response.items) }) })
      .catch((err) => {
        if (!active) return
        dispatch({ type: 'SET_SCORING_ERROR', payload: err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Unable to load rankings.' })
      })
      .finally(() => { if (active) setRankingsLoading(false) })
    return () => { active = false }
  }, [dispatch, mapRankings, state.projectId])

  const filtered = candidates
    .filter((c) => {
      const q = search.toLowerCase()
      const matchSearch = c.name.toLowerCase().includes(q) || c.email.toLowerCase().includes(q)
      const matchStatus = filterStatus === 'all' || c.status === filterStatus
      return matchSearch && matchStatus
    })
    .sort((a, b) => sortBy === 'rank' ? a.rank - b.rank : b.overallScore - a.overallScore)

  const updateStatus = (id: string, status: ScreeningStatus) =>
    dispatch({ type: 'UPDATE_CANDIDATE_STATUS', payload: { id, status } })

  // ─── Scoring & Ranking (POST /score -> POST /rank -> GET /rankings) ───
  const runScoring = async () => {
    if (state.isProcessing) return

    const prerequisiteError = scoringPrerequisitesMet(state)
    if (prerequisiteError) {
      dispatch({ type: 'SET_SCORING_ERROR', payload: prerequisiteError })
      return
    }

    const projectId = state.projectId!
    dispatch({ type: 'SET_SCORING_ERROR', payload: null })
    dispatch({ type: 'SET_PROCESSING', payload: true })
    dispatch({ type: 'SET_AI_PIPELINE_STEP', payload: 5 })

    try {
      // Step 1: POST /api/v1/projects/{project_id}/score
      const scoring = await api.scoreProject(projectId)

      // Step 2: POST /api/v1/projects/{project_id}/rank
      await api.rankProject(projectId)

      // Step 3: GET /api/v1/projects/{project_id}/rankings
      const rankingsData = await api.getRankings(projectId, { page_size: 100 })

      const mapped = mapRankings(rankingsData.items)

      dispatch({
        type: 'SET_SCORING_RESULT',
        payload: { scoring, candidates: mapped },
      })
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Scoring/Ranking failed'
      dispatch({ type: 'SET_SCORING_ERROR', payload: message })
    } finally {
      dispatch({ type: 'SET_PROCESSING', payload: false })
    }
  }

  // Stats
  const screened = candidates.filter((c) => c.status === 'screened').length
  const avgScore = candidates.length
    ? Math.round(candidates.reduce((s, c) => s + c.overallScore, 0) / candidates.length)
    : 0
  const topScore = candidates.length
    ? Math.max(...candidates.map((c) => c.overallScore))
    : 0

  const handleContinue = () => {
    if (!state.scoringComplete) return
    completeAndAdvance()
    navigate(`/projects/${state.projectId}/reports`)
  }

  return (
    <>
      {/* AI Explanation Drawer */}
      <ExplanationDrawer
        candidate={selectedCandidate}
        onClose={() => setSelectedCandidate(null)}
      />

      <motion.div variants={container} initial="hidden" animate="show" className="max-w-5xl mx-auto">

        {/* ── AI Pipeline Rail ── */}
        <motion.div variants={fadeUp}>
          <AIPipelineRail
            currentAIStep={
              state.scoringComplete
                ? AI_PIPELINE_STAGES.length + 1
                : state.isProcessing
                  ? state.aiPipelineStep
                  : 0
            }
            isProcessing={state.isProcessing}
          />
        </motion.div>

        {/* ── Page Header ── */}
        <motion.div variants={fadeUp} className="mb-5">
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-[26px] font-bold text-slate-800 mb-1">Candidate Ranking</h1>
              <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
                Run the full AI pipeline to extract, normalize, match, and rank all candidates
                against the job description. Click a candidate row to view the AI explanation.
              </p>
            </div>

            {/* Run Scoring / Status CTA */}
            {!state.isProcessing && (
              <motion.button
                className="btn-primary px-5 py-3 flex-shrink-0"
                onClick={runScoring}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                <Play size={15} />
                Run AI Scoring Engine
              </motion.button>
            )}

            {state.isProcessing && (
              <div className="flex items-center gap-2.5 bg-sky-50 border border-sky-100 rounded-xl px-4 py-3 flex-shrink-0">
                <motion.div
                  className="w-4 h-4 border-2 border-sky-500 border-t-transparent rounded-full"
                  animate={{ rotate: 360 }}
                  transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
                />
                <span className="text-[12px] font-semibold text-sky-700">
                  Scoring candidates…
                </span>
              </div>
            )}

          </div>
          {state.scoringError && (
            <p className="mt-2 text-[12px] text-red-500">{state.scoringError}</p>
          )}
        </motion.div>

        {/* ── Stats ── */}
        <motion.div variants={fadeUp} className="grid grid-cols-4 gap-3 mb-5">
          {[
            { icon: Users,         label: 'Total Candidates', value: candidates.length, color: 'text-sky-600',   bg: 'bg-sky-50'   },
            { icon: Star,          label: 'Screened',          value: screened,           color: 'text-green-600', bg: 'bg-green-50' },
            { icon: Trophy,        label: 'Avg Score',         value: `${avgScore}%`,     color: 'text-sky-600',   bg: 'bg-sky-50'   },
            { icon: LayoutDashboard, label: 'Top Score',       value: `${topScore}%`,     color: 'text-amber-600', bg: 'bg-amber-50' },
          ].map((s) => {
            const Icon = s.icon
            return (
              <motion.div
                key={s.label}
                className={`card p-4 ${s.bg} border-transparent`}
                whileHover={{ y: -2 }}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Icon size={14} className={s.color} />
                  <p className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">{s.label}</p>
                </div>
                <motion.p key={String(s.value)} className={`text-[24px] font-bold ${s.color}`} initial={{ scale: 0.85 }} animate={{ scale: 1 }}>
                  {s.value}
                </motion.p>
              </motion.div>
            )
          })}
        </motion.div>

        {/* ── Candidate Table ── */}
        <motion.div variants={fadeUp} className="card overflow-hidden mb-5">
          {/* Toolbar */}
          <div className="flex items-center gap-3 px-5 py-3.5 border-b border-slate-100">
            <div className="flex items-center gap-2 flex-1 bg-slate-50 rounded-lg px-3 py-2 border border-slate-100">
              <Search size={14} className="text-slate-400" />
              <input
                type="text"
                placeholder="Search candidates..."
                className="bg-transparent outline-none text-[13px] text-slate-600 flex-1 placeholder-slate-300"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <select
              className="text-[12px] border border-slate-200 rounded-lg px-2 py-2 text-slate-600 outline-none bg-white"
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as ScreeningStatus | 'all')}
            >
              <option value="all">All Status</option>
              <option value="screened">Screened</option>
              <option value="pending">Pending</option>
              <option value="rejected">Rejected</option>
            </select>

            <button
              onClick={() => setSortBy((s) => (s === 'rank' ? 'score' : 'rank'))}
              className="flex items-center gap-1.5 text-[12px] text-slate-500 hover:text-sky-600 px-3 py-2 rounded-lg hover:bg-sky-50 border border-slate-200 transition-colors"
            >
              <Filter size={13} />
              Sort: {sortBy === 'rank' ? 'Rank' : 'Score'}
            </button>

            <select
              className="text-[12px] border border-slate-200 rounded-lg px-2 py-2 text-slate-600 outline-none bg-white font-medium hover:border-sky-300 transition-colors"
              onChange={async (e) => {
                const val = e.target.value as 'csv' | 'excel' | 'json' | 'pdf' | ''
                if (!val || !state.projectId) return
                try {
                  const blob = await api.exportProjectData(state.projectId, val)
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = `project_${state.projectId}_rankings.${val === 'excel' ? 'xlsx' : val}`
                  a.click()
                  URL.revokeObjectURL(url)
                } catch (err) {
                  console.error('Export error:', err)
                }
                e.target.value = ''
              }}
              defaultValue=""
            >
              <option value="" disabled>Export Data...</option>
              <option value="csv">Export CSV</option>
              <option value="excel">Export Excel (.xlsx)</option>
              <option value="json">Export JSON</option>
              <option value="pdf">Export PDF</option>
            </select>
          </div>

          {/* Hint row */}
          {state.scoringComplete && (
            <div className="flex items-center gap-2 px-5 py-2.5 bg-sky-50/60 border-b border-sky-100">
              <Sparkles size={13} className="text-sky-500" />
              <p className="text-[11px] text-sky-700 font-medium">
                Click any candidate row to open the AI explanation drawer.
              </p>
            </div>
          )}

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Candidate</th>
                  <th>Score</th>
                  <th>Status</th>
                  <th>Action</th>
                  {state.scoringComplete && <th>AI Details</th>}
                </tr>
              </thead>
              <tbody>
                <AnimatePresence>
                  {filtered.map((candidate, idx) => (
                    <React.Fragment key={candidate.id}>
                      <motion.tr
                        key={candidate.id}
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        transition={{ delay: idx * 0.05 }}
                        className={state.scoringComplete ? 'cursor-pointer hover:bg-sky-50/40' : ''}
                        onClick={() => {
                          if (state.scoringComplete) setSelectedCandidate(candidate)
                        }}
                      >
                        <td>
                          <div className="flex items-center gap-1.5">
                            {candidate.rank <= 3 && (
                              <span>{candidate.rank === 1 ? '🥇' : candidate.rank === 2 ? '🥈' : '🥉'}</span>
                            )}
                            <span className="text-[13px] font-bold text-slate-400">#{candidate.rank}</span>
                          </div>
                        </td>
                        <td>
                          <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-sky-400 to-sky-600 flex items-center justify-center text-white font-bold text-[11px] flex-shrink-0">
                              {candidate.name.split(' ').map((n) => n[0]).join('')}
                            </div>
                            <div>
                              <p className="text-[13px] font-semibold text-slate-800">{candidate.name}</p>
                              <div className="flex items-center gap-1 text-[11px] text-slate-400">
                                <Mail size={10} />
                                <span>{candidate.email}</span>
                              </div>
                              {candidate.currentTitle && (
                                <div className="flex items-center gap-1 text-[11px] text-slate-400">
                                  <Briefcase size={10} />
                                  <span>{candidate.currentTitle}</span>
                                </div>
                              )}
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className={`score-badge ${getScoreClass(candidate.overallScore)}`}>
                            {candidate.overallScore}
                          </div>
                        </td>
                        <td>
                          <span className={STATUS_STYLES[candidate.status].cls}>
                            {STATUS_STYLES[candidate.status].label}
                          </span>
                        </td>
                        <td>
                          <select
                            className="text-[11px] border border-slate-200 rounded-lg px-2 py-1 text-slate-600 outline-none bg-white"
                            value={candidate.status}
                            onChange={(e) => {
                              e.stopPropagation()
                              updateStatus(candidate.id, e.target.value as ScreeningStatus)
                            }}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <option value="screened">Screen</option>
                            <option value="pending">Pending</option>
                            <option value="rejected">Reject</option>
                          </select>
                        </td>
                        {state.scoringComplete && (
                          <td>
                            <motion.button
                              className="flex items-center gap-1.5 text-[11px] font-semibold text-sky-600 hover:text-sky-700 px-2.5 py-1.5 rounded-lg hover:bg-sky-50 border border-sky-100 transition-colors"
                              onClick={(e) => {
                                e.stopPropagation()
                                setSelectedCandidate(candidate)
                              }}
                              whileHover={{ scale: 1.03 }}
                              whileTap={{ scale: 0.97 }}
                            >
                              <Sparkles size={12} />
                              Explain
                            </motion.button>
                          </td>
                        )}
                      </motion.tr>
                    </React.Fragment>
                  ))}
                </AnimatePresence>
              </tbody>
            </table>

            {!rankingsLoading && filtered.length === 0 && (
              <div className="py-12 text-center text-slate-400">
                <Users size={32} className="mx-auto mb-3 opacity-30" />
                <p className="text-[13px]">{search || filterStatus !== 'all' ? 'No candidates match your filter.' : 'No candidates have been ranked yet.'}</p>
              </div>
            )}
          </div>
        </motion.div>

        {/* ── Continue CTA ── */}
        <motion.div variants={fadeUp} className="flex justify-end">
          <motion.button
            className="btn-primary px-6"
            onClick={handleContinue}
            disabled={!state.scoringComplete}
            whileHover={state.scoringComplete ? { scale: 1.02 } : undefined}
            whileTap={state.scoringComplete ? { scale: 0.98 } : undefined}
          >
            Go to Recruiter Dashboard
            <ArrowRight size={15} />
          </motion.button>
        </motion.div>
      </motion.div>
    </>
  )
}
