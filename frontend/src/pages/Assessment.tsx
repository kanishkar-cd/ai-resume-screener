import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Award,
  CheckCircle2,
  ArrowLeft,
  RefreshCw,
  Copy,
  Check,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  Clock,
  UserCheck,
  FileCheck2,
  Send,
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api } from '@/api'

export default function Assessment() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { state, dispatch } = usePipeline()

  const [isSyncing, setIsSyncing] = useState(false)
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
      if (res && res.candidates && Array.isArray(res.candidates)) {
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
        setSyncStatusMsg('Polled status: No new updates available.')
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

  // Helper formatting routines
  const getBandBadgeClass = (band?: string | null) => {
    const b = (band || '').toUpperCase()
    if (b.includes('STRONG_PASS') || b.includes('EXCELLENT') || b.includes('BAND_A') || b === 'A') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
    if (b.includes('PASS') || b.includes('GOOD') || b.includes('BAND_B') || b === 'B') return 'bg-blue-50 text-blue-700 border-blue-200'
    if (b.includes('BORDERLINE') || b.includes('AVERAGE') || b.includes('BAND_C') || b === 'C') return 'bg-amber-50 text-amber-700 border-amber-200'
    if (b.includes('FAIL') || b.includes('BELOW') || b.includes('BAND_D') || b === 'D') return 'bg-rose-50 text-rose-700 border-rose-200'
    return 'bg-slate-100 text-slate-700 border-slate-200'
  }

  const formatTimestamp = (ts?: string | null) => {
    if (!ts) return null
    try {
      const dt = new Date(ts)
      return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    } catch {
      return ts
    }
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header Banner */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-teal-50 text-teal-700 text-xs font-semibold mb-2 border border-teal-100">
            <CheckCircle2 size={13} />
            Technical Assessment Handoff
          </div>
          <h1 className="text-xl font-extrabold text-slate-900">
            CD-Recruit Candidate Results
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Invited candidate assessment links and evaluation results for{' '}
            <span className="font-semibold text-slate-900">{reqTitle}</span> ({reqRef}).
          </p>
        </div>

        <div className="flex items-center gap-3 self-stretch md:self-auto">
          <button
            type="button"
            onClick={handleSyncResults}
            disabled={isSyncing}
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-teal-600 hover:bg-teal-700 active:bg-teal-800 text-white rounded-xl text-xs font-bold shadow-sm transition-all disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw size={14} className={isSyncing ? 'animate-spin' : ''} />
            {isSyncing ? 'Syncing Results...' : 'Sync Results'}
          </button>
        </div>
      </div>

      {/* Feedback Toast Banner */}
      {syncStatusMsg && (
        <div className="bg-teal-50 border border-teal-200 text-teal-800 text-xs font-semibold px-4 py-3 rounded-xl flex items-center gap-2 animate-fadeIn">
          <CheckCircle2 size={16} className="text-teal-600 flex-shrink-0" />
          <span>{syncStatusMsg}</span>
        </div>
      )}

      {/* Summary Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-sm flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center flex-shrink-0">
            <Award size={20} />
          </div>
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Invited</p>
            <p className="text-xl font-extrabold text-slate-900 mt-0.5">{totalInvited}</p>
          </div>
        </div>

        <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-sm flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center flex-shrink-0">
            <FileCheck2 size={20} />
          </div>
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Submitted</p>
            <p className="text-xl font-extrabold text-slate-900 mt-0.5">{submittedCount}</p>
          </div>
        </div>

        <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-sm flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-teal-50 text-teal-600 flex items-center justify-center flex-shrink-0">
            <CheckCircle2 size={20} />
          </div>
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Graded & Evaluated</p>
            <div className="flex items-baseline gap-1.5 mt-0.5">
              <p className="text-xl font-extrabold text-teal-700">{gradedCount}</p>
              {avgCompositeScore !== null && (
                <span className="text-[11px] font-bold text-teal-600 bg-teal-50 px-1.5 py-0.5 rounded border border-teal-100">
                  avg. {avgCompositeScore}%
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-sm flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center flex-shrink-0">
            <ShieldCheck size={20} />
          </div>
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Identity Verified</p>
            <p className="text-xl font-extrabold text-emerald-700 mt-0.5">{verifiedCount}</p>
          </div>
        </div>
      </div>

      {/* Assessment Table */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
            <CheckCircle2 size={16} className="text-teal-600" />
            Candidate Assessment Results & Handoff Status
          </h3>
          <span className="text-xs text-slate-500 font-medium">
            Showing {assessmentList.length} candidate record{assessmentList.length === 1 ? '' : 's'}
          </span>
        </div>

        {assessmentList.length === 0 ? (
          <div className="py-12 text-center text-xs text-slate-400">
            No candidates sent to assessment yet. Go to Shortlist to select and send candidates.
          </div>
        ) : (
          <div className="overflow-x-auto border border-slate-100 rounded-xl">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50 text-[11px] font-bold text-slate-400 uppercase border-b border-slate-100">
                  <th className="py-3 px-3 text-center w-10">#</th>
                  <th className="py-3 px-4">Candidate</th>
                  <th className="py-3 px-4">Handoff Link</th>
                  <th className="py-3 px-4 text-center">Session Status</th>
                  <th className="py-3 px-4 text-center">Identity</th>
                  <th className="py-3 px-4 text-center">Composite Score</th>
                  <th className="py-3 px-4 text-center">Decision</th>
                  <th className="py-3 px-4 text-right">Timestamps</th>
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
                      <td className="py-3.5 px-3 text-center">
                        <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-slate-100 text-slate-600 text-[11px] font-bold">
                          {idx + 1}
                        </span>
                      </td>
                      <td className="py-3.5 px-4">
                        <p className="font-bold text-slate-900">{item.candidateName}</p>
                        <p className="text-[11px] text-slate-400 mt-0.5">{item.email}</p>
                      </td>
                      <td className="py-3.5 px-4">
                        {item.assessmentLink ? (
                          <div className="flex items-center gap-2">
                            <a
                              href={item.assessmentLink}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 text-[11px] font-bold transition-colors border border-blue-100"
                            >
                              Open Test
                              <ExternalLink size={12} />
                            </a>
                            <button
                              type="button"
                              onClick={() => handleCopyLink(item.id, item.assessmentLink!)}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-[11px] font-medium transition-colors border border-slate-200 cursor-pointer"
                              title="Copy assessment link to clipboard"
                            >
                              {copiedId === item.id ? (
                                <>
                                  <Check size={12} className="text-emerald-600" />
                                  <span className="text-emerald-600 font-bold">Copied</span>
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
                          <span className="text-[11px] text-slate-400 font-mono">
                            {item.reqRef}
                          </span>
                        )}
                      </td>
                      <td className="py-3.5 px-4 text-center">
                        {isSubmitted ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-purple-50 text-purple-700 border border-purple-200 uppercase">
                            <CheckCircle2 size={11} />
                            Submitted
                          </span>
                        ) : isInProgress ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200 uppercase">
                            <Clock size={11} />
                            In Progress
                          </span>
                        ) : isExpired ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-rose-50 text-rose-700 border border-rose-200 uppercase">
                            Expired
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-600 border border-slate-200 uppercase">
                            Not Started
                          </span>
                        )}
                      </td>
                      <td className="py-3.5 px-4 text-center">
                        {item.isIdentityVerified === true || item.identityStatus?.toUpperCase() === 'VERIFIED' ? (
                          <span className="inline-flex items-center gap-1 text-emerald-700 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded-full text-[10px] font-bold">
                            <ShieldCheck size={12} />
                            Verified
                          </span>
                        ) : item.identityStatus?.toUpperCase() === 'FAILED' ? (
                          <span className="inline-flex items-center gap-1 text-rose-700 bg-rose-50 border border-rose-100 px-2 py-0.5 rounded-full text-[10px] font-bold">
                            <ShieldAlert size={12} />
                            Failed
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-slate-400 text-[10px] font-medium">
                            <Clock size={11} />
                            Pending
                          </span>
                        )}
                      </td>
                      <td className="py-3.5 px-4 text-center">
                        {compScore !== null ? (
                          <span className="text-[12px] font-extrabold text-teal-700 bg-teal-50 px-2 py-0.5 rounded border border-teal-100 inline-block">
                            {compScore}%
                          </span>
                        ) : (
                          <span className="text-slate-400 text-xs">—</span>
                        )}
                      </td>
                      <td className="py-3.5 px-4 text-center">
                        {item.decision && item.decision.toUpperCase() !== 'NONE' && item.decision.toUpperCase() !== 'NULL' ? (
                          <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase border ${
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
                      <td className="py-3.5 px-4 text-right">
                        {item.submittedAt ? (
                          <div className="text-[11px] text-slate-600">
                            <span className="text-[9px] text-slate-400 block font-normal">Submitted</span>
                            {formatTimestamp(item.submittedAt)}
                          </div>
                        ) : item.startedAt ? (
                          <div className="text-[11px] text-slate-600">
                            <span className="text-[9px] text-slate-400 block font-normal">Started</span>
                            {formatTimestamp(item.startedAt)}
                          </div>
                        ) : (
                          <div className="text-[11px] text-slate-400">
                            <span className="text-[9px] text-slate-400 block font-normal">Sent</span>
                            {item.sentAt || 'Recently'}
                          </div>
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
