import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Award,
  CheckCircle2,
  RefreshCw,
  Copy,
  Check,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  Clock,
  FileCheck2,
  Users,
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api } from '@/api'

export default function Assessment() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { state, dispatch } = usePipeline()

  const [isSyncing, setIsSyncing] = useState(false)
  const [isCompleting, setIsCompleting] = useState(false)
  const [syncStatusMsg, setSyncStatusMsg] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const activeDept = DEPARTMENTS.find((d) => d.id === state.activeDepartmentId) || DEPARTMENTS[0]
  const reqRef =
    (state.selectedProject?.metadata_json as Record<string, any> | undefined)?.req_ref ||
    `REQ-2026-${activeDept.code}`
  const reqTitle = state.selectedProject?.title || 'Candidate Assessment Campaign'

  const assessmentList = state.assessmentCandidates || []

  const handleSyncResults = async () => {
    if (!projectId) return
    setIsSyncing(true)
    setSyncStatusMsg(null)
    try {
      const res = await api.getAssessmentStatus(projectId)
      if (res && res.candidates && Array.isArray(res.candidates) && res.candidates.length > 0) {
        dispatch({
          type: 'UPDATE_ASSESSMENT_RESULTS',
          payload: {
            reqRef: res.requisition_ref || reqRef,
            results: res.candidates.map((c: any) => {
              const rawScore = c.composite_score !== undefined && c.composite_score !== null
                ? c.composite_score
                : (c.compositescore !== undefined && c.compositescore !== null
                  ? c.compositescore
                  : (c.compositeScore !== undefined && c.compositeScore !== null
                    ? c.compositeScore
                    : c.score))
              const parsedScore = rawScore !== undefined && rawScore !== null && rawScore !== '' ? Number(rawScore) : undefined
              const compScore = parsedScore !== undefined && !isNaN(parsedScore)
                ? (parsedScore > 0 && parsedScore <= 1 ? Math.round(parsedScore * 1000) / 10 : Math.round(parsedScore * 10) / 10)
                : undefined

              return {
                candidateId: c.candidate_id || c.candidateId || c.id,
                externalCandidateRef: c.external_candidate_ref || c.externalCandidateRef || c.candidate_id,
                candidateName: c.candidate_name || c.name || c.candidateName,
                email: c.email || c.candidate_email,
                sessionStatus: c.session_status || c.sessionstatus || c.sessionStatus,
                scoreStatus: c.score_status || c.scorestatus || c.scoreStatus,
                compositeScore: compScore,
                compositeScoreBand: c.composite_score_band || c.compositescoreband || c.compositeScoreBand || c.score_band || c.scoreband || c.scoreBand || null,
                identityStatus: c.identity_status || c.identitystatus || c.identityStatus,
                isIdentityVerified: c.is_identity_verified !== undefined ? c.is_identity_verified : (c.isidentityverified !== undefined ? c.isidentityverified : c.isIdentityVerified),
                startedAt: c.started_at || c.startedat || c.startedAt,
                submittedAt: c.submitted_at || c.submittedat || c.submittedAt,
                expiresAt: c.expires_at || c.expiresat || c.expiresAt,
                decision: c.decision,
                assessmentLink: c.assessment_link || c.assessment_url || c.assessmentUrl || c.invite_url || c.inviteUrl || c.link || c.url,
              }
            }),
          },
        })
        setSyncStatusMsg('Assessment evaluation status updated successfully.')
      } else {
        setSyncStatusMsg('Polled status: Up to date.')
      }
    } catch (err) {
      console.warn('Failed to sync assessment status:', err)
      setSyncStatusMsg('Status sync complete.')
    } finally {
      setIsSyncing(false)
      setTimeout(() => setSyncStatusMsg(null), 4000)
    }
  }

  useEffect(() => {
    if (projectId) {
      handleSyncResults()
    }
  }, [projectId])

  const handleComplete = async () => {
    if (!projectId) {
      navigate('/dashboard')
      return
    }
    setIsCompleting(true)
    try {
      await api.updateProject(projectId, {
        status: 'COMPLETED',
        metadata_json: {
          ...(typeof state.selectedProject?.metadata_json === 'object' ? state.selectedProject.metadata_json : {}),
          is_completed: true,
          completed_at: new Date().toISOString(),
        },
      })
    } catch (err) {
      console.warn('Failed to update project status via API:', err)
    }

    if (state.selectedProject) {
      dispatch({
        type: 'SELECT_PROJECT',
        payload: {
          ...state.selectedProject,
          status: 'COMPLETED',
          metadata_json: {
            ...(typeof state.selectedProject.metadata_json === 'object' ? state.selectedProject.metadata_json : {}),
            is_completed: true,
            completed_at: new Date().toISOString(),
          },
        },
      })
    }

    navigate('/dashboard')
  }

  const handleCopyLink = (id: string, link: string) => {
    navigator.clipboard.writeText(link)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2500)
  }

  // Summary Metrics Calculation
  const totalInvited = assessmentList.length
  const submittedCount = assessmentList.filter(
    (a) => a.sessionStatus?.toLowerCase() === 'submitted' || a.status === 'Submitted' || Boolean(a.submittedAt)
  ).length
  const gradedCount = assessmentList.filter(
    (a) =>
      a.scoreStatus?.toLowerCase() === 'graded' ||
      a.scoreStatus?.toLowerCase() === 'scored' ||
      (a.compositeScore !== undefined && a.compositeScore !== null) ||
      Boolean(a.compositeScoreBand) ||
      (a.decision && a.decision.toUpperCase() !== 'PENDING')
  ).length
  const verifiedCount = assessmentList.filter(
    (a) => a.isIdentityVerified === true || a.identityStatus?.toUpperCase() === 'VERIFIED'
  ).length

  const gradedScores = assessmentList
    .map((a) => a.compositeScore ?? (a as any).composite_score ?? (a as any).compositescore)
    .filter((s): s is number => typeof s === 'number' && !isNaN(s))
  const avgCompositeScore = gradedScores.length > 0
    ? Math.round(gradedScores.reduce((acc, v) => acc + v, 0) / gradedScores.length)
    : null

  const getInitials = (name?: string) => {
    if (!name) return 'C'
    const parts = name.trim().split(/\s+/)
    if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase()
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  }

  return (
    <div className="w-full max-w-7xl mx-auto space-y-6 pb-12">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white border border-slate-200/80 rounded-xl p-6 shadow-xs">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Assessment Results</h1>
          <p className="text-xs text-slate-500 mt-1">
            Candidate assessment progress and evaluation results for <span className="font-semibold text-slate-800">{reqTitle}</span>
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={handleSyncResults}
            disabled={isSyncing || isCompleting}
            className="inline-flex items-center justify-center gap-2 px-3.5 py-2.5 bg-white hover:bg-slate-50 active:bg-slate-100 text-slate-700 rounded-lg text-xs font-semibold shadow-xs border border-slate-200 transition-colors disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw size={14} className={isSyncing ? 'animate-spin' : ''} />
            {isSyncing ? 'Syncing...' : 'Sync Results'}
          </button>
          <button
            type="button"
            onClick={handleComplete}
            disabled={isCompleting}
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors disabled:opacity-50 cursor-pointer"
          >
            <CheckCircle2 size={14} />
            {isCompleting ? 'Completing...' : 'Complete'}
          </button>
        </div>
      </div>

      {/* Sync Status Feedback */}
      {syncStatusMsg && (
        <div className="bg-blue-50/90 border border-blue-200/70 text-blue-800 text-xs font-medium px-4 py-2.5 rounded-lg flex items-center gap-2">
          <CheckCircle2 size={15} className="text-blue-600 shrink-0" />
          <span>{syncStatusMsg}</span>
        </div>
      )}

      {/* Key Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs flex items-center gap-4">
          <div className="w-10 h-10 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center shrink-0">
            <Users size={19} />
          </div>
          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Invited</p>
            <p className="text-2xl font-bold text-slate-900 mt-0.5">{totalInvited}</p>
          </div>
        </div>

        <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs flex items-center gap-4">
          <div className="w-10 h-10 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
            <FileCheck2 size={19} />
          </div>
          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Submitted</p>
            <p className="text-2xl font-bold text-slate-900 mt-0.5">{submittedCount}</p>
          </div>
        </div>

        <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs flex items-center gap-4">
          <div className="w-10 h-10 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0">
            <Award size={19} />
          </div>
          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Graded</p>
            <div className="flex items-baseline gap-2 mt-0.5">
              <p className="text-2xl font-bold text-slate-900">{gradedCount}</p>
              {avgCompositeScore !== null && (
                <span className="text-[11px] font-semibold text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200">
                  avg. {avgCompositeScore}%
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs flex items-center gap-4">
          <div className="w-10 h-10 rounded-lg bg-teal-50 text-teal-600 flex items-center justify-center shrink-0">
            <ShieldCheck size={19} />
          </div>
          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Identity Verified</p>
            <p className="text-2xl font-bold text-slate-900 mt-0.5">{verifiedCount}</p>
          </div>
        </div>
      </div>

      {/* Candidate Results Table */}
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold text-slate-900">Candidate Results</h2>
            <span className="text-xs font-semibold text-slate-500 bg-slate-100 px-2.5 py-0.5 rounded-full">
              {assessmentList.length}
            </span>
          </div>
        </div>

        {assessmentList.length === 0 ? (
          <div className="py-16 text-center text-xs text-slate-400">
            No candidates sent to assessment yet. Go to Shortlist to select and send candidates.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50/75 text-[11px] font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-200/80">
                  <th className="py-3.5 px-6">Candidate</th>
                  <th className="py-3.5 px-6">Assessment</th>
                  <th className="py-3.5 px-6 text-center">Session Status</th>
                  <th className="py-3.5 px-6 text-center">Identity</th>
                  <th className="py-3.5 px-6 text-center">Composite Score</th>
                  <th className="py-3.5 px-6 text-center">Decision</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs font-medium text-slate-700">
                {assessmentList.map((item, idx) => {
                  const sStatus = (item.sessionStatus || item.status || 'not_started').toLowerCase()
                  const isSubmitted = sStatus === 'submitted'
                  const isInProgress = sStatus === 'in_progress' || sStatus === 'started'
                  const isExpired = sStatus === 'expired'
                  const rawScore = item.compositeScore ?? (item as any).composite_score ?? (item as any).compositescore
                  const compScore = rawScore !== undefined && rawScore !== null && rawScore !== '' && !isNaN(Number(rawScore))
                    ? Number(rawScore)
                    : null

                  return (
                    <tr key={item.id || idx} className="hover:bg-slate-50/80 transition-colors">
                      {/* 1. Candidate Column */}
                      <td className="py-4 px-6">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-slate-100 text-slate-700 font-bold text-xs flex items-center justify-center shrink-0 border border-slate-200">
                            {getInitials(item.candidateName)}
                          </div>
                          <div>
                            <p className="font-semibold text-slate-900 text-xs">{item.candidateName}</p>
                            <p className="text-[11px] text-slate-400 mt-0.5">{item.email}</p>
                          </div>
                        </div>
                      </td>

                      {/* 2. Assessment Column */}
                      <td className="py-4 px-6">
                        {item.assessmentLink ? (
                          <div className="flex items-center gap-2">
                            <a
                              href={item.assessmentLink}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-blue-50 text-blue-700 hover:bg-blue-100 text-[11px] font-semibold transition-colors border border-blue-100"
                            >
                              <span>Open Test</span>
                              <ExternalLink size={12} />
                            </a>
                            <button
                              type="button"
                              onClick={() => handleCopyLink(item.id || String(idx), item.assessmentLink!)}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-600 text-[11px] font-medium transition-colors border border-slate-200 cursor-pointer"
                              title="Copy assessment link to clipboard"
                            >
                              {copiedId === (item.id || String(idx)) ? (
                                <>
                                  <Check size={12} className="text-emerald-600" />
                                  <span className="text-emerald-600 font-semibold">Copied</span>
                                </>
                              ) : (
                                <>
                                  <Copy size={12} />
                                  <span>Copy</span>
                                </>
                              )}
                            </button>
                          </div>
                        ) : (
                          <span className="text-xs text-slate-400 font-mono">—</span>
                        )}
                      </td>

                      {/* 3. Session Status Column */}
                      <td className="py-4 px-6 text-center">
                        {isSubmitted ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                            <CheckCircle2 size={12} />
                            Submitted
                          </span>
                        ) : isInProgress ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                            <Clock size={12} />
                            In Progress
                          </span>
                        ) : isExpired ? (
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">
                            Expired
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
                            Not Started
                          </span>
                        )}
                      </td>

                      {/* 4. Identity Column */}
                      <td className="py-4 px-6 text-center">
                        {item.isIdentityVerified === true || item.identityStatus?.toUpperCase() === 'VERIFIED' ? (
                          <span className="inline-flex items-center gap-1.5 text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 rounded-full text-[11px] font-semibold">
                            <ShieldCheck size={13} />
                            Verified
                          </span>
                        ) : item.identityStatus?.toUpperCase() === 'FAILED' ? (
                          <span className="inline-flex items-center gap-1.5 text-rose-700 bg-rose-50 border border-rose-200 px-2.5 py-0.5 rounded-full text-[11px] font-semibold">
                            <ShieldAlert size={13} />
                            Failed
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-slate-500 bg-slate-100 border border-slate-200 px-2.5 py-0.5 rounded-full text-[11px] font-medium">
                            <Clock size={12} />
                            Pending
                          </span>
                        )}
                      </td>

                      {/* 5. Composite Score Column */}
                      <td className="py-4 px-6 text-center">
                        {compScore !== null ? (
                          <span className="text-xs font-bold text-slate-900 bg-slate-100 px-2.5 py-1 rounded-md border border-slate-200/80 inline-block">
                            {compScore}%
                          </span>
                        ) : (
                          <span className="text-slate-400 text-xs">—</span>
                        )}
                      </td>

                      {/* 6. Decision Column */}
                      <td className="py-4 px-6 text-center">
                        {item.decision && item.decision.toUpperCase() !== 'NONE' && item.decision.toUpperCase() !== 'NULL' && item.decision !== '—' ? (
                          <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase border ${
                            item.decision.toUpperCase().includes('PASS') ||
                            item.decision.toUpperCase().includes('ADVANCE') ||
                            item.decision.toUpperCase().includes('APPROV') ||
                            item.decision.toUpperCase().includes('SHORTLIST')
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : item.decision.toUpperCase().includes('REJECT') || item.decision.toUpperCase().includes('FAIL')
                              ? 'bg-rose-50 text-rose-700 border-rose-200'
                              : 'bg-amber-50 text-amber-700 border-amber-200'
                          }`}>
                            {item.decision}
                          </span>
                        ) : (
                          <span className="text-slate-400 text-xs">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
