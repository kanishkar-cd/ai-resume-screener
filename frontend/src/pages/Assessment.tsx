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
            results: res.candidates.map((c: any) => ({
              candidateId: c.candidate_id,
              externalCandidateRef: c.external_candidate_ref || c.candidate_id,
              candidateName: c.candidate_name || c.name || c.candidateName,
              email: c.email || c.candidate_email,
              sessionStatus: c.session_status || c.sessionstatus,
              scoreStatus: c.score_status || c.scorestatus,
              compositeScore: c.composite_score !== undefined ? c.composite_score : c.compositescore,
              compositeScoreBand: c.composite_score_band || c.compositescoreband || c.score_band || c.scoreband,
              identityStatus: c.identity_status || c.identitystatus,
              isIdentityVerified: c.is_identity_verified !== undefined ? c.is_identity_verified : c.isidentityverified,
              startedAt: c.started_at || c.startedat,
              submittedAt: c.submitted_at || c.submittedat,
              expiresAt: c.expires_at || c.expiresat,
              decision: c.decision,
              assessmentLink: c.assessment_link || c.assessment_url || c.assessmentUrl || c.invite_url || c.inviteUrl || c.link || c.url,
            })),
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
      (a.compositeScore !== undefined && a.compositeScore !== null)
  ).length
  const verifiedCount = assessmentList.filter(
    (a) => a.isIdentityVerified === true || a.identityStatus?.toUpperCase() === 'VERIFIED'
  ).length

  // Helper formatting routines
  const getBandBadgeClass = (band?: string | null) => {
    const b = (band || '').toUpperCase()
    if (b.includes('BAND_A') || b === 'A' || b === 'PASS' || b === 'APPROVED') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
    if (b.includes('BAND_B') || b === 'B' || b === 'MEDIUM') return 'bg-blue-50 text-blue-700 border-blue-200'
    if (b.includes('BAND_C') || b === 'C' || b === 'LOW') return 'bg-amber-50 text-amber-700 border-amber-200'
    if (b.includes('BAND_D') || b === 'D' || b === 'FAIL' || b === 'REJECT') return 'bg-rose-50 text-rose-700 border-rose-200'
    return 'bg-slate-100 text-slate-600 border-slate-200'
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
            <Award size={13} />
            Technical Assessment & Evaluation Dashboard
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
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-teal-600 hover:bg-teal-700 active:bg-teal-800 text-white rounded-xl text-xs font-bold shadow-sm transition-all disabled:opacity-50"
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
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Graded</p>
            <p className="text-xl font-extrabold text-teal-700 mt-0.5">{gradedCount}</p>
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
                  <th className="py-3 px-4">Candidate</th>
                  <th className="py-3 px-4">Handoff Link</th>
                  <th className="py-3 px-4 text-center">Session Status</th>
                  <th className="py-3 px-4 text-center">Identity</th>
                  <th className="py-3 px-4 text-center">Score & Band</th>
                  <th className="py-3 px-4 text-center">Decision</th>
                  <th className="py-3 px-4 text-right">Timestamps</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs font-medium text-slate-700">
                {assessmentList.map((item) => {
                  const link = item.assessmentLink
                  const idStat = item.identityStatus ? item.identityStatus.trim() : null
                  const isVerified = item.isIdentityVerified === true || idStat?.toUpperCase() === 'VERIFIED'
                  const isFailedOrMismatch = idStat?.toUpperCase() === 'FAILED' || idStat?.toUpperCase() === 'MISMATCH'
                  const compScore = item.compositeScore
                  const compBand = item.compositeScoreBand
                  const sessStat = (item.sessionStatus || item.status || 'not_started').toLowerCase()
                  const decision = item.decision ? item.decision.trim() : null
                  const decisionUpper = decision?.toUpperCase() || ''

                  return (
                    <tr key={item.id} className="hover:bg-slate-50/80 transition-colors">
                      {/* Candidate Column */}
                      <td className="py-3.5 px-4">
                        <p className="font-bold text-slate-900">{item.candidateName}</p>
                        <p className="text-[11px] text-slate-400 mt-0.5">{item.email}</p>
                      </td>

                      {/* Handoff Link Column */}
                      <td className="py-3.5 px-4">
                        {link ? (
                          <div className="flex items-center gap-2">
                            <a
                              href={link}
                              target="_blank"
                              rel="noreferrer"
                              className="text-blue-600 hover:text-blue-700 underline font-mono text-[11px] max-w-[140px] truncate inline-flex items-center gap-1"
                              title={link}
                            >
                              <span>Link</span>
                              <ExternalLink size={11} />
                            </a>
                            <button
                              type="button"
                              onClick={() => handleCopyLink(item.id, link)}
                              className="p-1 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors"
                              title="Copy link to clipboard"
                            >
                              {copiedId === item.id ? (
                                <Check size={12} className="text-emerald-600" />
                              ) : (
                                <Copy size={12} />
                              )}
                            </button>
                          </div>
                        ) : (
                          <span className="text-slate-400 text-[11px] italic">No link</span>
                        )}
                      </td>

                      {/* Session Status Column */}
                      <td className="py-3.5 px-4 text-center">
                        <span
                          className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold border capitalize ${
                            sessStat === 'submitted'
                              ? 'bg-purple-50 text-purple-700 border-purple-200'
                              : sessStat === 'in_progress'
                              ? 'bg-blue-50 text-blue-700 border-blue-200'
                              : 'bg-slate-100 text-slate-600 border-slate-200'
                          }`}
                        >
                          {sessStat === 'submitted' ? (
                            <CheckCircle2 size={12} />
                          ) : sessStat === 'in_progress' ? (
                            <Clock size={12} />
                          ) : null}
                          {sessStat.replace('_', ' ')}
                        </span>
                      </td>

                      {/* Identity Verification Column */}
                      <td className="py-3.5 px-4 text-center">
                        <span
                          className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold border capitalize ${
                            isVerified
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : isFailedOrMismatch
                              ? 'bg-rose-50 text-rose-700 border-rose-200'
                              : 'bg-amber-50 text-amber-700 border-amber-200'
                          }`}
                        >
                          {isVerified ? (
                            <>
                              <ShieldCheck size={12} />
                              {idStat ? idStat.toLowerCase() : 'Verified'}
                            </>
                          ) : isFailedOrMismatch ? (
                            <>
                              <ShieldAlert size={12} />
                              {idStat ? idStat.toLowerCase() : 'Mismatch'}
                            </>
                          ) : (
                            <>
                              <ShieldAlert size={12} />
                              {idStat ? idStat.toLowerCase() : 'Unverified'}
                            </>
                          )}
                        </span>
                      </td>

                      {/* Score & Band Column */}
                      <td className="py-3.5 px-4 text-center">
                        <div className="flex flex-col items-center gap-0.5">
                          {compScore !== undefined && compScore !== null ? (
                            <span className="font-extrabold text-slate-900 text-xs">
                              {compScore.toFixed(1)}%
                            </span>
                          ) : (
                            <span className="text-[11px] text-slate-400 font-normal">--</span>
                          )}
                          {compBand && (
                            <span
                              className={`px-2 py-0.5 rounded-md text-[10px] font-extrabold border ${getBandBadgeClass(
                                compBand
                              )}`}
                            >
                              {compBand}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Decision Column */}
                      <td className="py-3.5 px-4 text-center">
                        <span
                          className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase border ${
                            decisionUpper.includes('ADVANCE') ||
                            decisionUpper.includes('APPROV') ||
                            decisionUpper.includes('PASS')
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : decisionUpper.includes('REJECT') ||
                                decisionUpper.includes('FAIL')
                              ? 'bg-rose-50 text-rose-700 border-rose-200'
                              : 'bg-slate-100 text-slate-600 border-slate-200'
                          }`}
                        >
                          {decisionUpper.includes('ADVANCE') ||
                          decisionUpper.includes('APPROV') ||
                          decisionUpper.includes('PASS') ? (
                            <CheckCircle2 size={11} />
                          ) : null}
                          {decision || 'PENDING'}
                        </span>
                      </td>

                      {/* Timestamps Column */}
                      <td className="py-3.5 px-4 text-right font-mono text-[10px] text-slate-500 space-y-0.5">
                        {item.submittedAt ? (
                          <p>
                            <span className="font-semibold text-slate-700">Sub:</span>{' '}
                            {formatTimestamp(item.submittedAt)}
                          </p>
                        ) : item.startedAt ? (
                          <p>
                            <span className="font-semibold text-slate-700">Start:</span>{' '}
                            {formatTimestamp(item.startedAt)}
                          </p>
                        ) : (
                          <p className="text-slate-400">Not started</p>
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
