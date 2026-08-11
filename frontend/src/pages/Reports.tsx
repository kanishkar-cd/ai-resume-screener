import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Award, Download, FileSearch, ShieldAlert, TrendingUp } from 'lucide-react'
import { api, ApiError } from '@/api'
import type {
  CandidateInsights, CandidateRanking, CandidateScore, NormalizedJobDescription,
  ProjectAnalytics, ProjectDashboard,
} from '@/api'
import { EmptyState, PageHeader, ProgressIndicator, StatusBadge } from '@/components/ui/SaaS'
import { usePipeline } from '@/store/pipelineStore'

type ReportData = {
  rankings: CandidateRanking[]
  scores: CandidateScore[]
  dashboard: ProjectDashboard
  analytics: ProjectAnalytics
  job: NormalizedJobDescription | null
  insights: Record<string, CandidateInsights>
}

const decisionTone = (recommendation: string, knockout: boolean) =>
  knockout || recommendation === 'REJECT' ? 'danger' : recommendation === 'SHORTLIST' ? 'success' : 'warning'

const decisionLabel = (candidate: CandidateRanking) => {
  if (candidate.is_knocked_out) return 'Rejected · Knockout'
  if (candidate.recommendation === 'REJECT') return 'Rejected · Below recommendation threshold'
  return candidate.recommendation
}

const percent = (count: number, total: number) => total ? Math.round(count / total * 100) : 0

export default function Reports() {
  const { state } = usePipeline()
  const navigate = useNavigate()
  const [data, setData] = useState<ReportData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  useEffect(() => {
    if (!state.projectId) {
      setError('No active project is available for this report.')
      setLoading(false)
      return
    }
    let active = true
    setLoading(true)
    setError(null)
    const jobRequest = (state.jdDocumentId
      ? Promise.resolve({ id: state.jdDocumentId })
      : api.getJobDescription(state.projectId))
      .then((document) => api.getNormalizedDocument(document.id))
      .then((value) => 'job_title' in value ? value : null)
      .catch(() => null)

    Promise.all([
      api.getRankings(state.projectId, { page_size: 100 }),
      api.getProjectScores(state.projectId),
      api.getDashboard(state.projectId),
      api.getAnalytics(state.projectId),
      jobRequest,
    ])
      .then(async ([rankingPage, scores, dashboard, analytics, job]) => {
        const eligibleTop = rankingPage.items.filter((item) => !item.is_knocked_out).slice(0, 3)
        const insightResults = await Promise.all(eligibleTop.map(async (candidate) => {
          try { return [candidate.document_id, await api.getInsights(candidate.document_id)] as const }
          catch { return [candidate.document_id, null] as const }
        }))
        if (!active) return
        setData({
          rankings: rankingPage.items,
          scores,
          dashboard,
          analytics,
          job,
          insights: Object.fromEntries(insightResults.filter((entry): entry is readonly [string, CandidateInsights] => entry[1] !== null)),
        })
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Unable to load screening report.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [state.jdDocumentId, state.projectId])

  const report = useMemo(() => {
    if (!data) return null
    const total = data.rankings.length
    const counts = {
      shortlist: data.rankings.filter((item) => !item.is_knocked_out && item.recommendation === 'SHORTLIST').length,
      review: data.rankings.filter((item) => !item.is_knocked_out && item.recommendation === 'REVIEW').length,
      consider: data.rankings.filter((item) => !item.is_knocked_out && item.recommendation === 'CONSIDER').length,
      belowThreshold: data.rankings.filter((item) => !item.is_knocked_out && item.recommendation === 'REJECT').length,
      knockout: data.rankings.filter((item) => item.is_knocked_out).length,
    }
    const rejected = counts.belowThreshold + counts.knockout
    const averageSkills = total
      ? data.rankings.reduce((sum, item) => sum + item.skills_score, 0) / total
      : 0
    const missingMandatory = new Map<string, number>()
    data.rankings.filter((item) => item.is_knocked_out).forEach((item) => {
      const reason = item.knockout_reason?.replace(/^Missing mandatory skills:\s*/i, '') || ''
      reason.split(',').map((skill) => skill.trim()).filter(Boolean).forEach((skill) =>
        missingMandatory.set(skill, (missingMandatory.get(skill) || 0) + 1))
    })
    const commonMissing = [...missingMandatory.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]
    const componentLabels: Record<string, string> = {
      skills: 'Skills', experience: 'Experience', projects: 'Projects', education: 'Education',
      certifications: 'Certifications', languages: 'Languages',
    }
    const differentiators = Object.keys(componentLabels).map((key) => {
      const applicable = data.scores
        .map((score) => score.component_scores[key as keyof typeof score.component_scores])
        .filter((detail) => !/\(N\/A\)/i.test(detail.explanation) && !/against 0 required months/i.test(detail.explanation))
      const values = applicable.map((detail) => detail.score)
      return { key, range: values.length ? Math.max(...values) - Math.min(...values) : -1 }
    }).sort((a, b) => b.range - a.range)[0]
    return { total, counts, rejected, averageSkills, commonMissing, differentiator: differentiators?.range > 0 ? componentLabels[differentiators.key] : null }
  }, [data])

  const exportReport = async (format: 'csv' | 'excel' | 'json' | 'pdf') => {
    if (!state.projectId) return
    setExportError(null)
    try {
      const blob = await api.exportProjectData(state.projectId, format)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `project_${state.projectId}_report.${format === 'excel' ? 'xlsx' : format}`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Unable to export report.')
    }
  }

  if (loading) return <div className="card p-10 text-center text-[13px] text-slate-500">Loading screening report…</div>
  if (error) return <div className="card border-red-200 p-8 text-center text-[13px] text-red-600">{error}</div>
  if (!data || !report) return null
  if (report.total === 0 && data.scores.length > 0) return <EmptyState icon={FileSearch} title="Rankings unavailable" description="Candidate scores exist, but rankings have not been generated for this project." />
  if (report.total === 0) return <EmptyState icon={FileSearch} title="No candidates" description="Upload and process resumes before generating a screening report." />

  const distribution = [
    ['Shortlisted', report.counts.shortlist, 'bg-green-500'],
    ['Review', report.counts.review, 'bg-amber-500'],
    ['Consider', report.counts.consider, 'bg-blue-500'],
    ['Rejected', report.counts.belowThreshold, 'bg-red-400'],
    ['Knockout rejected', report.counts.knockout, 'bg-red-700'],
  ] as const
  const topEligible = data.rankings.filter((item) => !item.is_knocked_out).slice(0, 3)
  const belowThreshold = data.rankings.filter((item) => !item.is_knocked_out && item.recommendation === 'REJECT')
  const knockedOut = data.rankings.filter((item) => item.is_knocked_out)
  const insights = [
    report.counts.consider > 0 ? `${report.counts.consider} candidate${report.counts.consider === 1 ? '' : 's'} currently ${report.counts.consider === 1 ? 'falls' : 'fall'} into the Consider range.` : null,
    report.counts.knockout > 0 ? `${report.counts.knockout} candidate${report.counts.knockout === 1 ? '' : 's'} ${report.counts.knockout === 1 ? 'was' : 'were'} rejected by mandatory-requirement knockout rules.` : null,
    report.commonMissing ? `${report.commonMissing[0]} is the most common missing mandatory skill (${report.commonMissing[1]} candidate${report.commonMissing[1] === 1 ? '' : 's'}).` : null,
    report.differentiator ? `${report.differentiator} ${report.differentiator === 'Skills' || report.differentiator === 'Projects' || report.differentiator === 'Certifications' || report.differentiator === 'Languages' ? 'are' : 'is'} the largest differentiating factor in the current candidate pool.` : null,
  ].filter((item): item is string => Boolean(item))

  return <div className="mx-auto max-w-6xl space-y-6">
    <PageHeader
      title="Screening Report"
      description="Recruiter summary for the current job description and candidate pool."
      action={<div className="flex items-center gap-3">
        <div className="text-right"><p className="text-[12px] font-semibold text-slate-700">{data.job?.job_title || data.dashboard.project_summary.target_role}</p><p className="text-[11px] text-slate-400">{report.total} candidates · {Math.round(data.dashboard.pipeline_completion_percentage)}% complete</p></div>
        <select className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12px] text-slate-600" defaultValue="" onChange={(event) => { const value = event.target.value as 'csv'|'excel'|'json'|'pdf'|''; if (value) void exportReport(value); event.target.value = '' }}>
          <option value="" disabled>Export report</option><option value="csv">CSV</option><option value="excel">Excel</option><option value="json">JSON</option><option value="pdf">PDF</option>
        </select>
      </div>}
    />
    {exportError && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-[12px] text-red-700">{exportError}</p>}

    <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      {[
        ['Total Candidates', report.total, 'text-slate-900'], ['Recommended / Shortlisted', report.counts.shortlist, 'text-green-700'],
        ['Needs Review', report.counts.review + report.counts.consider, 'text-amber-700'], ['Rejected', report.rejected, 'text-red-700'],
        ['Average Score', `${data.analytics.average_score.toFixed(2)}%`, 'text-blue-700'],
      ].map(([label, value, color]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-[11px] font-semibold text-slate-500">{label}</p><p className={`mt-2 text-[24px] font-bold ${color}`}>{value}</p></div>)}
    </section>

    <section className="grid gap-5 lg:grid-cols-2">
      <div className="card p-5"><h2 className="text-[16px] font-bold text-slate-900">Candidate Distribution</h2><div className="mt-5 space-y-4">{distribution.map(([label, count, color]) => <div key={label}><div className="mb-1.5 flex justify-between text-[12px]"><span className="font-medium text-slate-600">{label}</span><span className="text-slate-500">{count} · {percent(count, report.total)}%</span></div><div className="h-1.5 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${color}`} style={{ width: `${percent(count, report.total)}%` }}/></div></div>)}</div></div>
      <div className="card p-5"><h2 className="text-[16px] font-bold text-slate-900">Score Overview</h2><div className="mt-5 grid grid-cols-2 gap-4">{[
        ['Average score', `${data.analytics.average_score.toFixed(2)}%`], ['Highest score', `${data.analytics.highest_score.toFixed(2)}%`],
        ['Lowest score', `${data.analytics.lowest_score.toFixed(2)}%`], ['Average skills match', `${report.averageSkills.toFixed(2)}%`],
        ['Knockout count', report.counts.knockout],
      ].map(([label, value]) => <div key={label} className="rounded-lg border border-slate-100 bg-slate-50 p-3"><p className="text-[11px] text-slate-500">{label}</p><p className="mt-1 text-[18px] font-bold text-slate-800">{value}</p></div>)}</div></div>
    </section>

    <section className="card p-5"><div className="flex items-center gap-2"><TrendingUp size={16} className="text-blue-600"/><h2 className="text-[16px] font-bold text-slate-900">Screening Insights</h2></div>{insights.length ? <ul className="mt-4 grid gap-3 md:grid-cols-2">{insights.map((item) => <li key={item} className="rounded-lg border border-slate-100 bg-slate-50 p-3 text-[12px] leading-relaxed text-slate-600">{item}</li>)}</ul> : <p className="mt-4 text-[12px] text-slate-500">No additional evidence-based insights are available.</p>}</section>

    <section className="card p-5"><div className="flex items-center gap-2"><ShieldAlert size={16} className="text-red-600"/><h2 className="text-[16px] font-bold text-slate-900">Rejection Analysis</h2></div><div className="mt-5 grid gap-5 lg:grid-cols-2">
      <div><h3 className="text-[12px] font-bold uppercase tracking-wider text-slate-500">Below recommendation threshold</h3><div className="mt-3 space-y-2">{belowThreshold.length ? belowThreshold.map((item) => <div key={item.document_id} className="rounded-lg border border-amber-200 bg-amber-50 p-3"><div className="flex justify-between"><p className="text-[12px] font-semibold text-slate-800">{item.candidate_name}</p><p className="text-[13px] font-bold text-amber-800">{item.final_score}</p></div><p className="mt-1 text-[11px] text-amber-800">Final score falls below the current recommendation threshold of 50.</p></div>) : <p className="text-[12px] text-slate-400">No eligible candidates were rejected by score.</p>}</div></div>
      <div><h3 className="text-[12px] font-bold uppercase tracking-wider text-slate-500">Knockout candidates</h3><div className="mt-3 space-y-2">{knockedOut.length ? knockedOut.map((item) => <div key={item.document_id} className="rounded-lg border border-red-200 bg-red-50 p-3"><div className="flex justify-between"><p className="text-[12px] font-semibold text-slate-800">{item.candidate_name}</p><p className="text-[13px] font-bold text-red-700">{item.final_score}</p></div><p className="mt-1 text-[11px] text-red-700">{item.knockout_reason || 'Mandatory requirement not satisfied'}</p><p className="mt-1 text-[10px] text-slate-500">Retained merit score: {item.final_score}</p></div>) : <p className="text-[12px] text-slate-400">No candidates were rejected by knockout.</p>}</div></div>
    </div></section>

    <section><div className="mb-3 flex items-center gap-2"><Award size={16} className="text-blue-600"/><h2 className="text-[16px] font-bold text-slate-900">Top Candidates</h2></div>{topEligible.length ? <div className="grid gap-4 lg:grid-cols-3">{topEligible.map((item) => <button key={item.document_id} onClick={() => navigate(`/projects/${state.projectId}/rankings`, { state: { selectedDocumentId: item.document_id } })} className="card p-5 text-left"><div className="flex justify-between"><span className="text-[12px] font-bold text-blue-600">#{item.rank_position}</span><StatusBadge tone={decisionTone(item.recommendation, item.is_knocked_out)}>{item.recommendation}</StatusBadge></div><p className="mt-3 text-[15px] font-bold text-slate-900">{item.candidate_name}</p><p className="mt-1 text-[24px] font-bold text-slate-900">{item.final_score}</p><div className="mt-3 space-y-2 text-[11px] text-slate-500"><div className="flex justify-between"><span>Skills match</span><span>{item.skills_score.toFixed(2)}%</span></div><ProgressIndicator value={item.skills_score}/><div className="flex justify-between"><span>Profile completeness</span><span>{item.confidence.toFixed(2)}%</span></div></div><p className="mt-4 line-clamp-3 text-[11px] leading-relaxed text-slate-500">{data.insights[item.document_id]?.summary || 'Screening explanation unavailable.'}</p></button>)}</div> : <EmptyState icon={Award} title="No eligible candidates" description="All ranked candidates were rejected by knockout rules." />}</section>

    <section className="card overflow-hidden"><div className="flex items-center justify-between border-b border-slate-100 px-5 py-4"><div><h2 className="text-[16px] font-bold text-slate-900">Candidate Report</h2><p className="mt-1 text-[11px] text-slate-500">Persisted scoring and ranking outcomes for this project.</p></div><Download size={16} className="text-slate-400"/></div><div className="overflow-x-auto"><table className="table-base"><thead><tr><th>Rank</th><th>Candidate</th><th>Score</th><th>Recommendation</th><th>Skills</th><th>Profile completeness</th><th>Screening status</th><th>Action</th></tr></thead><tbody>{data.rankings.map((item) => <tr key={item.document_id}><td className="font-bold text-slate-500">#{item.rank_position}</td><td><p className="font-semibold text-slate-800">{item.candidate_name}</p><p className="text-[11px] text-slate-400">{item.email || 'Email not provided'}</p></td><td className="font-bold text-slate-800">{item.final_score}</td><td><StatusBadge tone={decisionTone(item.recommendation, item.is_knocked_out)}>{item.recommendation}</StatusBadge></td><td>{item.skills_score.toFixed(2)}%</td><td>{item.confidence.toFixed(2)}%</td><td className="text-[11px] font-medium text-slate-600">{decisionLabel(item)}</td><td><button onClick={() => navigate(`/projects/${state.projectId}/rankings`, { state: { selectedDocumentId: item.document_id } })} className="text-[11px] font-semibold text-blue-600 hover:text-blue-800">View explanation</button></td></tr>)}</tbody></table></div></section>
  </div>
}
