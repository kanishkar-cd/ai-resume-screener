import { Check, Circle, LoaderCircle, ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { usePipeline } from '@/store/pipelineStore'
import { PageHeader, ProgressIndicator, StatusBadge } from '@/components/ui/SaaS'

export default function Processing() {
  const { state }=usePipeline(); const navigate=useNavigate()
  const total=state.resumeDocumentIds.length; const normalized=Object.values(state.resumeProcessing).filter(r=>r.normalized).length
  const processing=Object.values(state.resumeProcessing).some(r=>['parsing','extracting','normalizing'].includes(r.phase))
  const stages=[['Parsing',normalized===total&&total>0,processing],['Extraction',normalized===total&&total>0,processing],['Normalization',normalized===total&&total>0,processing],['Scoring',state.scoringComplete,false],['Ranking',state.candidates.length>0,false]] as const
  const completed=stages.filter(([,done])=>done).length; const progress=Math.round(completed/stages.length*100); const finished=completed===stages.length
  return <div><PageHeader title={finished?'Screening complete':'Processing candidates'} description={finished?'Candidate scoring and ranking are ready.':'Analyzing resumes against the job requirements.'}/>
    <section className="bg-white border border-slate-200 rounded-2xl p-8 mb-8"><div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-5"><div><p className="text-[12px] text-slate-500">Overall progress</p><p className="text-[32px] font-semibold tracking-tight mt-1">{progress}%</p></div><div className="text-left md:text-right"><p className="text-[12px] text-slate-500">Candidates processed</p><p className="text-[16px] font-semibold mt-1">{normalized} of {total}</p></div></div><ProgressIndicator value={progress}/></section>
    <section className="bg-white border border-slate-200 rounded-2xl divide-y divide-slate-100">{stages.map(([label,done,active])=><div key={label} className="flex items-center justify-between px-6 py-5"><div className="flex items-center gap-3">{done?<span className="w-7 h-7 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center"><Check size={14}/></span>:active?<span className="w-7 h-7 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center"><LoaderCircle size={14} className="animate-spin"/></span>:<span className="w-7 h-7 rounded-full bg-slate-50 text-slate-300 flex items-center justify-center"><Circle size={13}/></span>}<span className="text-[13px] font-medium text-slate-800">{label}</span></div><StatusBadge tone={done?'success':active?'info':'neutral'}>{done?'Complete':active?'Processing':'Pending'}</StatusBadge></div>)}</section>
    <div className="flex justify-end mt-7"><button className="btn-primary" onClick={()=>navigate(`/projects/${state.projectId}/rankings`)}>View candidate rankings <ArrowRight size={14}/></button></div>
  </div>
}
