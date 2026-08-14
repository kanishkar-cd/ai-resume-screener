import { useParams, useNavigate } from 'react-router-dom'
import {
  Award,
  CheckCircle2,
  Clock,
  Send,
  Building2,
  FileText,
  Download,
  Calendar,
  ArrowLeft,
  Sparkles,
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'

export default function Assessment() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { state } = usePipeline()

  const activeDept = DEPARTMENTS.find((d) => d.id === state.activeDepartmentId) || DEPARTMENTS[0]
  const reqRef = `REQ-2026-${activeDept.code}-042`
  const reqTitle = state.selectedProject?.title || 'Senior Full-Stack Engineer Requisition'

  // Assessment candidates list from store or default mock candidates
  const assessmentList =
    state.assessmentCandidates && state.assessmentCandidates.length > 0
      ? state.assessmentCandidates
      : [
          {
            id: 'c1',
            candidateName: 'JEGADHEES J',
            email: 'jegadhees@example.com',
            currentTitle: 'Lead Software Engineer',
            reqRef: reqRef,
            meritScore: 31.62,
            rank: 1,
            status: 'Completed' as const,
            sentAt: '2026-08-12',
            techScore: 88,
            codingScore: 94,
            overallResult: 'PASSED' as const,
          },
          {
            id: 'c2',
            candidateName: 'Vaishnavi S',
            email: 'vaishnavi@example.com',
            currentTitle: 'Senior Frontend Developer',
            reqRef: reqRef,
            meritScore: 29.79,
            rank: 2,
            status: 'Completed' as const,
            sentAt: '2026-08-12',
            techScore: 82,
            codingScore: 88,
            overallResult: 'PASSED' as const,
          },
          {
            id: 'c3',
            candidateName: 'KARTHIK SRINIVASAN',
            email: 'karthik@example.com',
            currentTitle: 'Full-Stack Developer',
            reqRef: reqRef,
            meritScore: 24.79,
            rank: 3,
            status: 'Pending' as const,
            sentAt: '2026-08-12',
            techScore: 75,
            codingScore: 78,
            overallResult: 'UNDER_REVIEW' as const,
          },
        ]

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Navigation Breadcrumb */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-500">
          <button
            type="button"
            onClick={() => navigate(`/departments/${activeDept.id}`)}
            className="hover:text-blue-600 transition-colors"
          >
            {activeDept.name}
          </button>
          <span>/</span>
          <button
            type="button"
            onClick={() => navigate(`/projects/${projectId}/shortlist`)}
            className="hover:text-blue-600 transition-colors"
          >
            Shortlist
          </button>
          <span>/</span>
          <span className="text-slate-900 font-bold">Assessment Handoff</span>
        </div>

        <button
          type="button"
          onClick={() => navigate(`/projects/${projectId}/shortlist`)}
          className="inline-flex items-center gap-2 px-4 py-2 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200"
        >
          <ArrowLeft size={15} />
          Back to Shortlist
        </button>
      </div>

      {/* Header Banner */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-teal-50 text-teal-700 text-xs font-semibold mb-2 border border-teal-100">
            <Award size={13} />
            Technical Assessment Handoff
          </div>
          <h1 className="text-xl font-extrabold text-slate-900">
            Assessment Handoff & Test Results
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Tracking invited candidates for <span className="font-semibold text-slate-900">{reqTitle}</span> ({reqRef}).
          </p>
        </div>

        {/* Status Pills */}
        <div className="flex items-center gap-4 bg-slate-50 p-3 rounded-xl border border-slate-100 self-stretch md:self-auto justify-around">
          <div className="text-center px-3">
            <p className="text-[10px] font-bold text-slate-400 uppercase">Invited</p>
            <p className="text-xl font-extrabold text-slate-900 mt-0.5">{assessmentList.length}</p>
          </div>
          <div className="h-8 w-[1px] bg-slate-200" />
          <div className="text-center px-3">
            <p className="text-[10px] font-bold text-slate-400 uppercase">Completed</p>
            <p className="text-xl font-extrabold text-emerald-600 mt-0.5">
              {assessmentList.filter((a) => a.status === 'Completed').length}
            </p>
          </div>
          <div className="h-8 w-[1px] bg-slate-200" />
          <div className="text-center px-3">
            <p className="text-[10px] font-bold text-slate-400 uppercase">Passed</p>
            <p className="text-xl font-extrabold text-teal-600 mt-0.5">
              {assessmentList.filter((a) => a.overallResult === 'PASSED').length}
            </p>
          </div>
        </div>
      </div>

      {/* Assessment Table */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm space-y-4">
        <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
          <CheckCircle2 size={16} className="text-teal-600" />
          Candidate Assessment Status & Evaluation Scores
        </h3>

        <div className="overflow-x-auto border border-slate-100 rounded-xl">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 text-[11px] font-bold text-slate-400 uppercase border-b border-slate-100">
                <th className="py-3 px-4">Candidate</th>
                <th className="py-3 px-4">Req Ref</th>
                <th className="py-3 px-4 text-center">Status</th>
                <th className="py-3 px-4 text-center">Tech MCQs</th>
                <th className="py-3 px-4 text-center">Coding Practical</th>
                <th className="py-3 px-4 text-center">Result</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs font-medium text-slate-700">
              {assessmentList.map((item) => (
                <tr key={item.id} className="hover:bg-slate-50/80 transition-colors">
                  <td className="py-3.5 px-4">
                    <p className="font-bold text-slate-900">{item.candidateName}</p>
                    <p className="text-[11px] text-slate-400 mt-0.5">{item.email}</p>
                  </td>
                  <td className="py-3.5 px-4 font-mono text-[11px] font-semibold text-slate-600">
                    {item.reqRef}
                  </td>
                  <td className="py-3.5 px-4 text-center">
                    <span
                      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold ${
                        item.status === 'Completed'
                          ? 'bg-emerald-50 text-emerald-700'
                          : 'bg-amber-50 text-amber-700'
                      }`}
                    >
                      {item.status === 'Completed' ? <CheckCircle2 size={12} /> : <Clock size={12} />}
                      {item.status}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 text-center font-extrabold text-slate-900">
                    {item.techScore || 80} / 100
                  </td>
                  <td className="py-3.5 px-4 text-center font-extrabold text-slate-900">
                    {item.codingScore || 85} / 100
                  </td>
                  <td className="py-3.5 px-4 text-center">
                    <span
                      className={`inline-block px-2.5 py-1 rounded-full text-[11px] font-extrabold ${
                        item.overallResult === 'PASSED'
                          ? 'bg-teal-50 text-teal-700'
                          : 'bg-amber-50 text-amber-700'
                      }`}
                    >
                      {item.overallResult}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 text-right space-x-2">
                    <button
                      type="button"
                      onClick={() => alert(`Downloading assessment package for ${item.candidateName}...`)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 bg-slate-100 text-slate-700 rounded-lg text-xs font-semibold hover:bg-slate-200"
                    >
                      <Download size={13} />
                      Report
                    </button>
                    <button
                      type="button"
                      onClick={() => alert(`Scheduling interview for ${item.candidateName}...`)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-bold hover:bg-blue-700"
                    >
                      <Calendar size={13} />
                      Schedule
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
