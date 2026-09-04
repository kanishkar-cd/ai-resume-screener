import { useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Building2,
  Calendar,
  CheckCircle2,
  ChevronRight,
  Download,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  Filter,
  Layers,
  ListOrdered,
  Loader2,
  Search,
  TrendingUp,
  UserCheck,
  UserX,
  Users,
  XCircle,
} from 'lucide-react'
import { api, CandidateRanking, CandidateScore, Project } from '@/api'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { Candidate } from '@/types'

function mapCandidateToRanking(c: Candidate, projId: string): CandidateRanking {
  const isKnockedOut = Boolean(c.isKnockedOut)
  const rec = (
    c.recommendation ||
    (isKnockedOut || c.status === 'rejected'
      ? 'REJECT'
      : c.status === 'screened'
        ? 'SHORTLIST'
        : 'REVIEW')
  ).toUpperCase() as 'SHORTLIST' | 'REVIEW' | 'REJECT'

  return {
    id: c.id,
    project_id: projId,
    document_id: c.documentId || c.id,
    candidate_name: c.name || 'Candidate',
    email: c.email || null,
    rank_position: c.rank || 1,
    percentile: c.percentile ?? 0,
    final_score: c.overallScore || 0,
    recommendation: rec,
    confidence: c.confidence ?? 1.0,
    is_knocked_out: isKnockedOut,
    knockout_reason: c.knockoutReason || null,
    skills_score: c.scores?.find((s) => s.criterionId === 'skills')?.score ?? 0,
    experience_score: c.scores?.find((s) => s.criterionId === 'experience')?.score ?? 0,
    previous_rank: null,
    rank_change: 0,
    created_at: c.scoredAt ? c.scoredAt.toISOString() : new Date().toISOString(),
  }
}

function getExperienceLevel(proj?: Project | null): 'Fresher' | 'Experienced' {
  if (!proj) return 'Fresher'
  if (proj.metadata_json && typeof proj.metadata_json.experience_level === 'string') {
    const level = proj.metadata_json.experience_level.toLowerCase()
    if (level.includes('experienced')) return 'Experienced'
    if (level.includes('fresher')) return 'Fresher'
  }
  if (proj.description) {
    const desc = proj.description.toLowerCase()
    if (desc.includes('experienced')) return 'Experienced'
    if (desc.includes('fresher')) return 'Fresher'
  }
  if (proj.title) {
    const title = proj.title.toLowerCase()
    if (title.includes('experienced')) return 'Experienced'
    if (title.includes('fresher')) return 'Fresher'
  }
  return 'Fresher'
}

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '—'
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

export default function Reports() {
  const { projectId: routeProjectId } = useParams<{ projectId: string }>()
  const { state } = usePipeline()
  const navigate = useNavigate()

  const projectId = routeProjectId || state.projectId
  const isMatchingSession = Boolean(
    projectId && (state.projectId === projectId || state.selectedProject?.id === projectId)
  )

  const [project, setProject] = useState<Project | any | null>(() => {
    if (isMatchingSession && state.selectedProject) return state.selectedProject
    return null
  })

  const [rankings, setRankings] = useState<CandidateRanking[]>(() => {
    if (isMatchingSession && state.candidates && state.candidates.length > 0) {
      return state.candidates.map((c) => mapCandidateToRanking(c, projectId!))
    }
    return []
  })

  const [scores, setScores] = useState<CandidateScore[]>([])

  const [assessmentCandidates, setAssessmentCandidates] = useState<any[]>(() => {
    if (isMatchingSession && state.assessmentCandidates && state.assessmentCandidates.length > 0) {
      return state.assessmentCandidates
    }
    return []
  })

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('ALL')

  useEffect(() => {
    if (!projectId) {
      setError('No requisition ID provided for this report.')
      setLoading(false)
      return
    }

    let active = true
    setLoading(true)
    setError(null)

    Promise.all([
      api.getProject(projectId).catch(() => null),
      api.getRankings(projectId, { page_size: 100 }).catch(() => ({ items: [], total: 0 })),
      api.getProjectScores(projectId).catch(() => []),
      api.getAssessmentStatus(projectId).catch(() => ({ candidates: [] })),
    ])
      .then(([projRes, rankingRes, scoreRes, assessRes]) => {
        if (!active) return

        // 1. Project metadata: API response > matching session project
        if (projRes) {
          setProject(projRes)
        } else if (isMatchingSession && state.selectedProject) {
          setProject(state.selectedProject)
        }

        // 2. Rankings: API items > matching session candidates fallback
        const apiRankings = rankingRes?.items || []
        if (apiRankings.length > 0) {
          setRankings(apiRankings)
        } else if (isMatchingSession && state.candidates && state.candidates.length > 0) {
          setRankings(state.candidates.map((c) => mapCandidateToRanking(c, projectId)))
        } else {
          setRankings([])
        }

        // 3. Project scores: API scores > empty
        setScores(scoreRes || [])

        // 4. Assessment candidates: API candidates > matching session assessment candidates fallback
        const apiAssess = assessRes?.candidates || []
        if (apiAssess.length > 0) {
          setAssessmentCandidates(apiAssess)
        } else if (isMatchingSession && state.assessmentCandidates && state.assessmentCandidates.length > 0) {
          setAssessmentCandidates(state.assessmentCandidates)
        } else {
          setAssessmentCandidates([])
        }
      })
      .catch((err) => {
        if (!active) return
        if (isMatchingSession && state.candidates && state.candidates.length > 0) {
          setRankings(state.candidates.map((c) => mapCandidateToRanking(c, projectId)))
          if (state.selectedProject) setProject(state.selectedProject)
          if (state.assessmentCandidates && state.assessmentCandidates.length > 0) {
            setAssessmentCandidates(state.assessmentCandidates)
          }
          setError(null)
        } else {
          setError(err instanceof Error ? err.message : 'Failed to load requisition report.')
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [projectId, isMatchingSession, state.candidates, state.selectedProject, state.assessmentCandidates])

  // Candidate Journey & Summary Calculation
  const metrics = useMemo(() => {
    const totalParticipated = rankings.length

    // 1. Rejected During Resume Screening
    const rejectedResume = rankings.filter(
      (r) => r.is_knocked_out || r.recommendation === 'REJECT'
    ).length

    // 2. Shortlisted After Resume Screening
    const shortlistedResume = rankings.filter(
      (r) => !r.is_knocked_out && r.recommendation !== 'REJECT'
    ).length

    // Map assessments by document_id / email / external ref / candidate name
    const assessMap = new Map<string, any>()
    for (const a of assessmentCandidates) {
      if (a.candidate_id) assessMap.set(String(a.candidate_id), a)
      if (a.candidateId) assessMap.set(String(a.candidateId), a)
      if (a.id) assessMap.set(String(a.id), a)
      if (a.external_candidate_ref) assessMap.set(String(a.external_candidate_ref), a)
      if (a.externalCandidateRef) assessMap.set(String(a.externalCandidateRef), a)
      if (a.email) assessMap.set(String(a.email).trim().toLowerCase(), a)
      if (a.candidate_name) assessMap.set(String(a.candidate_name).trim().toLowerCase(), a)
      if (a.candidateName) assessMap.set(String(a.candidateName).trim().toLowerCase(), a)
    }

    // 3. Shortlisted After Assessment
    let shortlistedAssessment = 0
    let assessmentScoresSum = 0
    let assessmentScoresCount = 0

    for (const r of rankings) {
      const isResumeRej = r.is_knocked_out || r.recommendation === 'REJECT'
      if (isResumeRej) continue

      const a =
        assessMap.get(String(r.document_id)) ||
        (r.email ? assessMap.get(String(r.email).trim().toLowerCase()) : undefined) ||
        assessMap.get(String(r.candidate_name).trim().toLowerCase())

      if (a) {
        const rawScore = a.composite_score ?? a.compositeScore ?? a.compositescore ?? a.score
        const score = typeof rawScore === 'number' ? rawScore : (rawScore ? Number(rawScore) : null)
        if (score !== null && !isNaN(score)) {
          assessmentScoresSum += score
          assessmentScoresCount++
        }
        const sess = (a.session_status || a.sessionStatus || '').toLowerCase()
        const scStat = (a.score_status || a.scoreStatus || '').toLowerCase()
        const dec = (a.decision || '').toUpperCase()
        const band = (a.composite_score_band || a.compositeScoreBand || a.compositescoreband || a.score_band || '').toUpperCase()

        const isPassed = (
          dec === 'SHORTLIST' || dec === 'PASS' || dec === 'APPROVE' || dec === 'ADVANCE' ||
          band.includes('BAND_A') || band.includes('BAND_B') || band.includes('EXCELLENT') || band.includes('GOOD') ||
          ((scStat === 'graded' || scStat === 'scored') && score !== null && score >= 60)
        ) && sess !== 'not_started'

        if (isPassed) {
          shortlistedAssessment++
        }
      }
    }

    // 4. Final Shortlisted & Final Rejected
    const finalShortlisted = shortlistedAssessment
    const finalRejected = totalParticipated - finalShortlisted

    // Averages
    const avgResumeScore =
      totalParticipated > 0
        ? rankings.reduce((sum, r) => sum + (r.final_score || 0), 0) / totalParticipated
        : 0

    const avgAssessmentScore =
      assessmentScoresCount > 0
        ? assessmentScoresSum / assessmentScoresCount
        : 0

    const pct = (n: number) =>
      totalParticipated > 0 ? Math.round((n / totalParticipated) * 100) : 0

    return {
      totalParticipated,
      rejectedResume,
      pctRejectedResume: pct(rejectedResume),
      shortlistedResume,
      pctShortlistedResume: pct(shortlistedResume),
      shortlistedAssessment,
      pctShortlistedAssessment: pct(shortlistedAssessment),
      finalRejected,
      pctFinalRejected: pct(finalRejected),
      finalShortlisted,
      pctFinalShortlisted: pct(finalShortlisted),
      avgResumeScore: Math.round(avgResumeScore * 10) / 10,
      avgAssessmentScore: Math.round(avgAssessmentScore * 10) / 10,
      assessMap,
    }
  }, [rankings, assessmentCandidates])

  // Candidate Detailed Rows
  const candidateRows = useMemo(() => {
    return rankings.map((r) => {
      const a =
        metrics.assessMap.get(String(r.document_id)) ||
        (r.email ? metrics.assessMap.get(String(r.email).trim().toLowerCase()) : undefined) ||
        metrics.assessMap.get(String(r.candidate_name).trim().toLowerCase())

      const isKnockedOut = r.is_knocked_out
      const isResumeRejected = isKnockedOut || r.recommendation === 'REJECT'
      const resumeStatus = isKnockedOut
        ? 'Knocked Out'
        : r.recommendation === 'SHORTLIST'
          ? 'Shortlisted'
          : r.recommendation === 'REVIEW'
            ? 'Needs Review'
            : 'Rejected'

      let assessmentScore: string | number = '—'
      let assessmentStatus = 'Not Started'
      let finalStatus: 'Final Shortlisted' | 'Final Rejected' | 'Under Review' | 'Not Attended' = 'Final Rejected'

      if (isResumeRejected) {
        finalStatus = 'Final Rejected'
        assessmentStatus = 'Not Invited'
      } else if (a) {
        const rawScore = a.composite_score ?? a.compositeScore ?? a.compositescore ?? a.score
        const score = typeof rawScore === 'number' ? rawScore : (rawScore ? Number(rawScore) : null)
        const band = a.composite_score_band || a.compositeScoreBand || a.compositescoreband || a.score_band || a.scoreband

        if (score !== null && !isNaN(score)) {
          assessmentScore = `${Math.round(score)}%`
        } else {
          assessmentScore = '—'
        }

        const sess = (a.session_status || a.sessionStatus || '').toLowerCase()
        const scStat = (a.score_status || a.scoreStatus || '').toLowerCase()
        const dec = (a.decision || '').toUpperCase()

        if (dec === 'SHORTLIST' || dec === 'PASS' || dec === 'APPROVE' || dec === 'ADVANCE') {
          assessmentStatus = 'Shortlisted'
        } else if (dec === 'REJECT' || dec === 'FAIL') {
          assessmentStatus = 'Rejected'
        } else if (scStat === 'graded' || scStat === 'scored' || (score !== null && !isNaN(score))) {
          assessmentStatus = score !== null && score >= 60 ? 'Shortlisted' : 'Graded'
        } else if (sess === 'submitted' || sess === 'completed') {
          assessmentStatus = 'Submitted'
        } else if (sess === 'in_progress' || sess === 'started') {
          assessmentStatus = 'In Progress'
        } else {
          assessmentStatus = 'Not Started'
        }

        // Determine Final Status accurately based on assessment participation and outcome
        if (dec === 'REJECT' || dec === 'FAIL') {
          finalStatus = 'Final Rejected'
        } else if (dec === 'SHORTLIST' || dec === 'PASS' || dec === 'APPROVE' || dec === 'ADVANCE') {
          finalStatus = 'Final Shortlisted'
        } else if (assessmentStatus === 'Graded' && score !== null && score >= 60) {
          finalStatus = 'Final Shortlisted'
        } else if (assessmentStatus === 'Graded' && score !== null && score < 60) {
          finalStatus = 'Final Rejected'
        } else if (assessmentStatus === 'Submitted') {
          finalStatus = 'Under Review'
        } else if (assessmentStatus === 'In Progress') {
          finalStatus = 'Under Review'
        } else {
          // Candidate was not started / did not attend
          finalStatus = 'Not Attended'
        }
      } else {
        finalStatus = 'Not Attended'
        assessmentStatus = 'Not Started'
      }

      return {
        id: r.document_id,
        name: r.candidate_name || 'Candidate',
        resumeScore: r.final_score,
        resumeStatus,
        isResumeRejected,
        assessmentScore,
        assessmentStatus,
        finalStatus,
      }
    })
  }, [rankings, metrics.assessMap])

  // Filtered Table Rows
  const filteredRows = useMemo(() => {
    return candidateRows.filter((row) => {
      const matchesSearch = row.name.toLowerCase().includes(searchTerm.toLowerCase())
      const matchesStatus =
        statusFilter === 'ALL' ||
        (statusFilter === 'SHORTLISTED' && row.finalStatus === 'Final Shortlisted') ||
        (statusFilter === 'REJECTED' && row.finalStatus === 'Final Rejected')

      return matchesSearch && matchesStatus
    })
  }, [candidateRows, searchTerm, statusFilter])

  const exportReport = async (format: 'csv' | 'excel' | 'json' | 'pdf') => {
    if (!projectId) return
    setExportError(null)
    try {
      const blob = await api.exportProjectData(projectId, format)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${project?.title || 'requisition'}_report.${format === 'excel' ? 'xlsx' : format}`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Unable to export report.')
    }
  }

  const dept = DEPARTMENTS.find((d) => d.name === project?.department) || DEPARTMENTS[0]

  if (loading) {
    return (
      <div className="py-24 text-center text-xs text-slate-400 font-medium flex items-center justify-center gap-2">
        <Loader2 size={18} className="animate-spin text-blue-600" />
        <span>Loading requisition report...</span>
      </div>
    )
  }

  if (error || !project) {
    return (
      <div className="p-8 max-w-5xl mx-auto space-y-4">
        <button
          type="button"
          onClick={() => navigate('/dashboard')}
          className="text-xs text-slate-500 hover:text-blue-600 font-semibold flex items-center gap-1 transition-colors cursor-pointer"
        >
          <ArrowLeft size={13} />
          <span>Back to Dashboard</span>
        </button>
        <div className="p-6 bg-red-50 border border-red-200 rounded-2xl text-red-700 text-xs font-semibold">
          <p className="text-sm font-bold">Unable to load requisition report</p>
          <p className="text-xs text-red-600 mt-1">{error || 'Requisition not found.'}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-8 max-w-[1440px] mx-auto space-y-6">
      {/* Breadcrumb Hierarchy */}
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-400">
        <button
          type="button"
          onClick={() => navigate('/dashboard')}
          className="hover:text-blue-600 transition-colors cursor-pointer"
        >
          Overview
        </button>
        <ChevronRight size={13} className="text-slate-300" />
        <button
          type="button"
          onClick={() => navigate(`/dashboard?dept=${encodeURIComponent(dept.name)}`)}
          className="hover:text-blue-600 transition-colors cursor-pointer"
        >
          {dept.name}
        </button>
        <ChevronRight size={13} className="text-slate-300" />
        <span className="text-slate-700 font-bold">Requisition Report</span>
      </div>

      {/* Top Header Card: Requisition Details */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="px-2.5 py-0.5 rounded-md bg-slate-100 text-slate-700 text-xs font-bold font-mono">
              {project.department || 'General'}
            </span>
            <span className="px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-700 text-xs font-bold border border-blue-200/70">
              {getExperienceLevel(project)}
            </span>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-blue-50 text-blue-700 border border-blue-200/60">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
              Completed
            </span>
          </div>

          <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">
            {project.title}
          </h1>

          <div className="flex items-center gap-4 text-xs text-slate-500 font-medium">
            <span>Target Role: <strong className="text-slate-700 font-bold">{project.target_role || '—'}</strong></span>
            <span>•</span>
            <span>Created: <strong className="text-slate-700 font-semibold">{formatDate(project.created_at)}</strong></span>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0 self-start md:self-auto">
          <button
            type="button"
            onClick={() => navigate(`/projects/${project.id}/rankings`)}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold transition-colors cursor-pointer"
          >
            <ListOrdered size={14} />
            <span>View Rankings</span>
          </button>

          <select
            className="rounded-xl border border-slate-200/90 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-2xs cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500/20"
            defaultValue=""
            onChange={(e) => {
              const val = e.target.value as 'csv' | 'excel' | 'json' | 'pdf' | ''
              if (val) void exportReport(val)
              e.target.value = ''
            }}
          >
            <option value="" disabled>Export Report</option>
            <option value="csv">Export as CSV</option>
            <option value="excel">Export as Excel</option>
            <option value="pdf">Export as PDF</option>
            <option value="json">Export as JSON</option>
          </select>
        </div>
      </div>

      {exportError && (
        <div className="p-3 bg-red-50 text-red-700 text-xs rounded-xl font-medium border border-red-200/80">
          {exportError}
        </div>
      )}

      {/* Candidate Journey Funnel Stages */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-slate-100">
          <div>
            <h2 className="text-sm font-bold text-slate-900 tracking-tight">Candidate Journey Summary</h2>
            <p className="text-xs text-slate-400 mt-0.5">End-to-end funnel conversion through screening and technical assessment</p>
          </div>
          <div className="flex items-center gap-4 text-xs font-semibold">
            <div className="flex items-center gap-1.5">
              <span className="text-slate-400">Avg Resume Match:</span>
              <span className="text-blue-600 font-extrabold">{metrics.avgResumeScore}%</span>
            </div>
            <span className="text-slate-300">|</span>
            <div className="flex items-center gap-1.5">
              <span className="text-slate-400">Avg Assessment:</span>
              <span className="text-emerald-600 font-extrabold">{metrics.avgAssessmentScore}%</span>
            </div>
          </div>
        </div>

        {/* 6 Funnel Stage Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 pt-1">
          {/* Stage 1: Participated */}
          <div className="p-3.5 rounded-xl border border-slate-200/80 bg-slate-50/50 flex flex-col justify-between space-y-2">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">1. Participated</span>
            <div>
              <p className="text-2xl font-extrabold text-slate-900">{metrics.totalParticipated}</p>
              <p className="text-[11px] text-slate-500 font-medium">100% total pool</p>
            </div>
          </div>

          {/* Stage 2: Rejected Resume */}
          <div className="p-3.5 rounded-xl border border-rose-100 bg-rose-50/30 flex flex-col justify-between space-y-2">
            <span className="text-[10px] font-bold text-rose-500 uppercase tracking-wider">2. Resume Rejected</span>
            <div>
              <p className="text-2xl font-extrabold text-rose-700">{metrics.rejectedResume}</p>
              <p className="text-[11px] text-rose-600 font-medium">{metrics.pctRejectedResume}% screened out</p>
            </div>
          </div>

          {/* Stage 3: Shortlisted Resume */}
          <div className="p-3.5 rounded-xl border border-blue-100 bg-blue-50/30 flex flex-col justify-between space-y-2">
            <span className="text-[10px] font-bold text-blue-500 uppercase tracking-wider">3. Resume Shortlist</span>
            <div>
              <p className="text-2xl font-extrabold text-blue-700">{metrics.shortlistedResume}</p>
              <p className="text-[11px] text-blue-600 font-medium">{metrics.pctShortlistedResume}% advanced</p>
            </div>
          </div>

          {/* Stage 4: Shortlisted Assessment */}
          <div className="p-3.5 rounded-xl border border-teal-100 bg-teal-50/30 flex flex-col justify-between space-y-2">
            <span className="text-[10px] font-bold text-teal-600 uppercase tracking-wider">4. Assessment Pass</span>
            <div>
              <p className="text-2xl font-extrabold text-teal-700">{metrics.shortlistedAssessment}</p>
              <p className="text-[11px] text-teal-600 font-medium">{metrics.pctShortlistedAssessment}% qualified</p>
            </div>
          </div>

          {/* Stage 5: Final Rejected */}
          <div className="p-3.5 rounded-xl border border-slate-200/80 bg-slate-50/50 flex flex-col justify-between space-y-2">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">5. Final Rejected</span>
            <div>
              <p className="text-2xl font-extrabold text-slate-700">{metrics.finalRejected}</p>
              <p className="text-[11px] text-slate-500 font-medium">{metrics.pctFinalRejected}% cumulative</p>
            </div>
          </div>

          {/* Stage 6: Final Shortlisted */}
          <div className="p-3.5 rounded-xl border border-emerald-200 bg-emerald-50/50 flex flex-col justify-between space-y-2 shadow-2xs">
            <span className="text-[10px] font-bold text-emerald-700 uppercase tracking-wider">6. Final Shortlisted</span>
            <div>
              <p className="text-2xl font-extrabold text-emerald-800">{metrics.finalShortlisted}</p>
              <p className="text-[11px] text-emerald-700 font-bold">{metrics.pctFinalShortlisted}% select rate</p>
            </div>
          </div>
        </div>
      </div>

      {/* Candidate Results Table */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-bold text-slate-900 tracking-tight">Candidate Results</h2>
            <span className="px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-700 text-[11px] font-bold">
              {filteredRows.length} candidates
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {/* Status Tabs */}
            <div className="flex items-center bg-slate-100 p-0.5 rounded-xl text-xs font-semibold text-slate-600">
              <button
                type="button"
                onClick={() => setStatusFilter('ALL')}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${statusFilter === 'ALL'
                    ? 'bg-white text-slate-900 shadow-2xs font-bold'
                    : 'hover:text-slate-900'
                  }`}
              >
                All ({candidateRows.length})
              </button>
              <button
                type="button"
                onClick={() => setStatusFilter('SHORTLISTED')}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${statusFilter === 'SHORTLISTED'
                    ? 'bg-white text-emerald-700 shadow-2xs font-bold'
                    : 'hover:text-slate-900'
                  }`}
              >
                Shortlisted ({metrics.finalShortlisted})
              </button>
              <button
                type="button"
                onClick={() => setStatusFilter('REJECTED')}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${statusFilter === 'REJECTED'
                    ? 'bg-white text-rose-700 shadow-2xs font-bold'
                    : 'hover:text-slate-900'
                  }`}
              >
                Rejected ({metrics.finalRejected})
              </button>
            </div>

            {/* Search Input */}
            <div className="relative min-w-[220px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search candidate name..."
                className="w-full pl-8 pr-3.5 py-1.5 bg-slate-50 border border-slate-200/80 rounded-xl text-xs font-medium text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 placeholder:text-slate-400 transition-all"
              />
            </div>
          </div>
        </div>

        {filteredRows.length === 0 ? (
          <div className="py-12 text-center text-xs text-slate-400 font-medium">
            No candidates match the filter criteria.
          </div>
        ) : (
          <div className="overflow-x-auto border border-slate-100 rounded-xl">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50/80 text-[10px] font-bold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                  <th className="py-3 px-4.5">Candidate Name</th>
                  <th className="py-3 px-4 text-center">Resume Score</th>
                  <th className="py-3 px-4 text-center">Resume Screening Status</th>
                  <th className="py-3 px-4 text-center">Assessment Score</th>
                  <th className="py-3 px-4 text-center">Assessment Status</th>
                  <th className="py-3 px-4.5 text-center">Final Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs font-medium text-slate-700">
                {filteredRows.map((row) => (
                  <tr key={row.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="py-3.5 px-4.5 font-bold text-slate-900">
                      {row.name}
                    </td>

                    <td className="py-3.5 px-4 text-center">
                      <span className="font-bold text-slate-900">{row.resumeScore}%</span>
                    </td>

                    <td className="py-3.5 px-4 text-center">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${row.isResumeRejected
                            ? 'bg-rose-50 text-rose-700 border-rose-200/70'
                            : 'bg-emerald-50 text-emerald-700 border-emerald-200/70'
                          }`}
                      >
                        {row.resumeStatus}
                      </span>
                    </td>

                    <td className="py-3.5 px-4 text-center">
                      <span className="font-bold text-slate-800">{row.assessmentScore}</span>
                    </td>

                    <td className="py-3.5 px-4 text-center">
                      <span className="inline-block px-2.5 py-0.5 rounded-md bg-slate-100 text-slate-700 text-[10px] font-bold">
                        {row.assessmentStatus}
                      </span>
                    </td>

                    <td className="py-3.5 px-4.5 text-center">
                      <span
                        className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-bold border ${row.finalStatus === 'Final Shortlisted'
                            ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                            : row.finalStatus === 'Final Rejected'
                              ? 'bg-rose-50 text-rose-700 border-rose-200'
                              : row.finalStatus === 'Not Attended'
                                ? 'bg-slate-100 text-slate-600 border-slate-200'
                                : 'bg-amber-50 text-amber-700 border-amber-200'
                          }`}
                      >
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${row.finalStatus === 'Final Shortlisted'
                              ? 'bg-emerald-500'
                              : row.finalStatus === 'Final Rejected'
                                ? 'bg-rose-500'
                                : row.finalStatus === 'Not Attended'
                                  ? 'bg-slate-400'
                                  : 'bg-amber-500'
                            }`}
                        />
                        {row.finalStatus}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
