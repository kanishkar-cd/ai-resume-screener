import { useParams, useNavigate } from 'react-router-dom'
import {
  Award,
  CheckCircle2,
  Clock,
  Send,
  Building2,
  FileText,
  Download,
  ArrowLeft,
  Sparkles,
  ExternalLink,
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'

export default function Assessment() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { state } = usePipeline()

  const activeDept = DEPARTMENTS.find((d) => d.id === state.activeDepartmentId) || DEPARTMENTS[0]
  const reqRef = (state.selectedProject?.metadata_json as Record<string, any> | undefined)?.req_ref || `REQ-2026-${activeDept.code}`



  const reqTitle = state.selectedProject?.title || 'Senior Full-Stack Engineer Requisition'

  // Assessment candidates list from store or empty array
  const assessmentList = state.assessmentCandidates || []

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
            CD-Recruit Assessment Links
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Invited candidate assessment links for <span className="font-semibold text-slate-900">{reqTitle}</span> ({reqRef}).
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
            <p className="text-[10px] font-bold text-slate-400 uppercase">Active Links</p>
            <p className="text-xl font-extrabold text-teal-600 mt-0.5">
              {assessmentList.filter((a) => Boolean(a.assessmentLink)).length}
            </p>
          </div>
        </div>
      </div>

      {/* Assessment Table */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm space-y-4">
        <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
          <CheckCircle2 size={16} className="text-teal-600" />
          Candidate Assessment Links & Handoff Status
        </h3>

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
                  <th className="py-3 px-4">Req Ref</th>
                  <th className="py-3 px-4 text-center">Status</th>
                  <th className="py-3 px-4">Assessment Link</th>
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
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-teal-50 text-teal-700 border border-teal-100">
                        <CheckCircle2 size={12} />
                        {item.status || 'Sent'}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 max-w-xs truncate">
                      {item.assessmentLink ? (
                        <a
                          href={item.assessmentLink}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-mono text-[11px] text-teal-600 hover:underline truncate block"
                          title={item.assessmentLink}
                        >
                          {item.assessmentLink}
                        </a>
                      ) : (
                        <span className="text-slate-400 text-[11px] italic">Link unavailable</span>
                      )}
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      {item.assessmentLink ? (
                        <a
                          href={item.assessmentLink}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1.5 px-3.5 py-1.5 bg-teal-600 text-white rounded-lg text-xs font-bold hover:bg-teal-700 transition-colors shadow-sm"
                        >
                          <ExternalLink size={13} />
                          Open Assessment
                        </a>
                      ) : (
                        <span className="text-xs text-slate-400 font-medium">Link unavailable</span>
                      )}
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

