import React, { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  LayoutDashboard,
  Search,
  Download,
  Filter,
  ChevronDown,
  ChevronUp,
  Briefcase,
  Mail,
  Trophy,
  Users,
  Star,
} from 'lucide-react'
import { usePipeline } from '@/store/pipelineStore'
import { Candidate, ScreeningStatus } from '@/types'
import { api, ProjectDashboard, ProjectAnalytics, CandidateRanking } from '@/api'
import { useLocation } from 'react-router-dom'

const fadeUp = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0 } }
const container = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } }

const STATUS_STYLES: Record<ScreeningStatus, { cls: string; label: string }> = {
  screened: { cls: 'status-badge status-screened', label: 'Screened' },
  pending: { cls: 'status-badge status-pending', label: 'Pending' },
  rejected: { cls: 'status-badge status-rejected', label: 'Rejected' },
}

function getScoreClass(score: number) {
  if (score >= 80) return 'score-high'
  if (score >= 60) return 'score-med'
  return 'score-low'
}

function rankingToStatus(recommendation: string, isKnockedOut: boolean): ScreeningStatus {
  if (isKnockedOut || recommendation === 'REJECT') return 'rejected'
  if (recommendation === 'SHORTLIST') return 'screened'
  return 'pending'
}

export default function RecruiterDashboard() {
  const isReports = useLocation().pathname.endsWith('/reports')
  const { state, dispatch } = usePipeline()
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState<ScreeningStatus | 'all'>('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<'rank' | 'score'>('rank')
  
  const [dashboard, setDashboard] = useState<ProjectDashboard | null>(null)
  const [analytics, setAnalytics] = useState<ProjectAnalytics | null>(null)
  const [fetchedCandidates, setFetchedCandidates] = useState<Candidate[]>([])

  useEffect(() => {
    if (!state.projectId) return
    let active = true

    Promise.all([
      api.getDashboard(state.projectId).catch(() => null),
      api.getAnalytics(state.projectId).catch(() => null),
      api.getRankings(state.projectId).catch(() => null),
    ]).then(([dashData, analyticsData, rankingsData]) => {
      if (!active) return
      if (dashData) setDashboard(dashData)
      if (analyticsData) setAnalytics(analyticsData)

      if (rankingsData && rankingsData.items.length > 0) {
        const mapped: Candidate[] = rankingsData.items.map((r: CandidateRanking) => ({
          id: r.document_id,
          name: r.candidate_name || 'Candidate',
          email: r.email || '',
          resumeFile: r.document_id,
          overallScore: Math.round(r.final_score),
          rank: r.rank_position,
          status: rankingToStatus(r.recommendation, r.is_knocked_out),
          extractedFields: [],
          scores: [
            { criterionId: 'skills', label: 'Skills', score: Math.round(r.skills_score), weight: 0, weightedScore: 0 },
            { criterionId: 'experience', label: 'Experience', score: Math.round(r.experience_score), weight: 0, weightedScore: 0 },
          ],
          scoredAt: new Date(r.created_at),
        }))
        setFetchedCandidates(mapped)
      }
    })

    return () => { active = false }
  }, [state.projectId, state.scoringComplete])

  // Project-scoped backend/store results only.
  const candidates: Candidate[] = state.candidates.length > 0
    ? state.candidates
    : fetchedCandidates.length > 0
      ? fetchedCandidates
      : []

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

  // Real stats calculation
  const totalCandidatesCount = candidates.length > 0 ? candidates.length : (dashboard?.project_summary.total_candidates ?? analytics?.total_candidates ?? 0)
  const screenedCount = candidates.length > 0
    ? candidates.filter((c) => c.status === 'screened').length
    : (analytics ? (analytics.recommendation_distribution?.SHORTLIST || 0) : 0)
  const avgScoreVal = candidates.length > 0
    ? Math.round(candidates.reduce((s, c) => s + c.overallScore, 0) / candidates.length)
    : (analytics ? Math.round(analytics.average_score) : 0)
  const topScoreVal = candidates.length > 0
    ? Math.max(...candidates.map((c) => c.overallScore))
    : (analytics ? Math.round(analytics.highest_score) : 0)
  const lowestScoreVal = candidates.length > 0
    ? Math.min(...candidates.map((c) => c.overallScore))
    : (analytics ? Math.round(analytics.lowest_score) : 0)
  const reviewCount = candidates.length > 0
    ? candidates.filter((c) => c.status === 'pending').length
    : (analytics ? (analytics.recommendation_distribution?.REVIEW ?? analytics.recommendation_distribution?.CONSIDER ?? 0) : 0)
  const rejectedCount = candidates.length > 0
    ? candidates.filter((c) => c.status === 'rejected').length
    : (analytics ? (analytics.recommendation_distribution?.REJECT || 0) : 0)

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="max-w-5xl mx-auto">
      <motion.div variants={fadeUp} className="mb-5">
        <h1 className="text-[30px] font-bold tracking-tight text-slate-900 mb-2">{isReports ? 'Reports' : 'Candidates'}</h1>
        <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
          A concise view of screening outcomes and candidate performance for this project.
        </p>
      </motion.div>

      {/* Stats */}
      <motion.div variants={fadeUp} className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { icon: Users, label: 'Total Candidates', value: totalCandidatesCount, color: 'text-blue-600', bg: 'bg-blue-50/80 border-blue-100/80' },
          { icon: Star, label: 'Screened', value: screenedCount, color: 'text-emerald-600', bg: 'bg-emerald-50/80 border-emerald-100/80' },
          { icon: Users, label: 'Needs Review', value: reviewCount, color: 'text-amber-600', bg: 'bg-amber-50/80 border-amber-100/80' },
          { icon: Users, label: 'Rejected', value: rejectedCount, color: 'text-red-600', bg: 'bg-red-50/80 border-red-100/80' },
        ].map((s) => {
          const Icon = s.icon
          return (
            <motion.div
              key={s.label}
              className={`rounded-2xl border p-5 ${s.bg}`}
              whileHover={{ y: -2 }}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <Icon size={14} className={s.color} />
                <p className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">{s.label}</p>
              </div>
              <motion.p key={String(s.value)} className={`text-[26px] font-extrabold ${s.color}`} initial={{ scale: 0.85 }} animate={{ scale: 1 }}>
                {s.value}
              </motion.p>
            </motion.div>
          )
        })}
      </motion.div>

      {/* Table */}
      <motion.div variants={fadeUp} className="card overflow-hidden">
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
                a.download = `project_${state.projectId}_dashboard.${val === 'excel' ? 'xlsx' : val}`
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
                <th></th>
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
                      className="cursor-pointer"
                      onClick={() => setExpanded(expanded === candidate.id ? null : candidate.id)}
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
                      <td>
                        {expanded === candidate.id ? (
                          <ChevronUp size={15} className="text-sky-500" />
                        ) : (
                          <ChevronDown size={15} className="text-slate-300" />
                        )}
                      </td>
                    </motion.tr>

                    {/* Expanded score breakdown */}
                    <AnimatePresence>
                      {expanded === candidate.id && (
                        <motion.tr
                          key={`expanded-${candidate.id}`}
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                        >
                          <td colSpan={6} className="p-0">
                            <motion.div
                              initial={{ height: 0 }}
                              animate={{ height: 'auto' }}
                              exit={{ height: 0 }}
                              className="overflow-hidden"
                            >
                              <div className="px-6 py-4 bg-sky-50/70 border-t border-sky-100">
                                <p className="text-[11px] font-bold text-sky-600 uppercase tracking-widest mb-3">
                                  Score Breakdown
                                </p>
                                <div className="grid grid-cols-5 gap-3">
                                  {candidate.scores.map((s) => (
                                    <div key={s.criterionId} className="bg-white rounded-xl p-3 shadow-sm border border-sky-100">
                                      <p className="text-[10px] text-slate-400 mb-1 font-medium">{s.label}</p>
                                      <p className="text-[18px] font-bold text-sky-600">{s.score}</p>
                                      <div className="progress-track mt-1.5">
                                        <motion.div
                                          className="progress-fill"
                                          initial={{ width: 0 }}
                                          animate={{ width: `${s.score}%` }}
                                          transition={{ duration: 0.6, delay: 0.1 }}
                                        />
                                      </div>
                                      <p className="text-[10px] text-slate-400 mt-1">Weight: {s.weight}%</p>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </motion.div>
                          </td>
                        </motion.tr>
                      )}
                    </AnimatePresence>
                  </React.Fragment>
                ))}

              </AnimatePresence>
            </tbody>
          </table>

          {filtered.length === 0 && (
            <div className="py-12 text-center text-slate-400">
              <Users size={32} className="mx-auto mb-3 opacity-30" />
              <p className="text-[13px]">No candidates match your filter.</p>
            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  )
}
