import { useEffect, useRef, useState } from 'react'
import { FileText, Users, Activity, Trophy, ArrowRight, Upload } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api'
import { usePipeline } from '@/store/pipelineStore'
import { PageHeader, ProgressIndicator, StatCard, StatusBadge } from '@/components/ui/SaaS'

export default function ProjectOverview() {
  const { state } = usePipeline(); const navigate = useNavigate()
  const [jd,setJd]=useState(false); const [resumeCount,setResumeCount]=useState(0); const [scores,setScores]=useState<number[]>([])
  const loadedProjectRef=useRef<string|null>(null)
  useEffect(()=>{ if(!state.projectId||loadedProjectRef.current===state.projectId)return; loadedProjectRef.current=state.projectId; api.getJobDescription(state.projectId).then(()=>setJd(true)).catch(()=>setJd(false)); api.listProjectResumes(state.projectId).then(r=>setResumeCount(r.total)).catch(()=>setResumeCount(0)); api.getProjectScores(state.projectId).then(r=>setScores(r.map(s=>s.final_score))).catch(()=>setScores([])) },[state.projectId])
  if(!state.projectId)return null
  const ranked=state.candidates.length>0; const average=scores.length?Math.round(scores.reduce((a,b)=>a+b,0)/scores.length):0
  const resumesReady=resumeCount>0 && state.resumeDocumentIds.every(id=>state.resumeProcessing[id]?.normalized)
  const stages=[['Job Description',jd],['Resumes',resumeCount>0],['Ranking',ranked],['Reports',ranked]] as const
  const completed=stages.filter(([,done])=>done).length; const progress=Math.round(completed/stages.length*100)
  const next=!jd?'job-description':resumeCount===0?'resumes':!ranked?'rankings':'reports'
  const nextLabel=!jd?'Upload job description':resumeCount===0?'Upload resumes':!ranked?'View candidate rankings':'View reports'
  return <div><PageHeader title="Project overview" description="Monitor this hiring campaign and continue the screening workflow." action={!jd?<button className="btn-primary" onClick={()=>navigate(`/projects/${state.projectId}/job-description`)}><Upload size={15}/> Upload JD</button>:undefined}/>
    <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5 mb-10"><StatCard icon={Users} label="Candidates" value={resumeCount}/><StatCard icon={FileText} label="JD status" value={jd?'Ready':'Not uploaded'}/><StatCard icon={Activity} label="Processing" value={progress===100?'Complete':`${progress}%`}/><StatCard icon={Trophy} label="Average score" value={scores.length?`${average}%`:'—'}/></div>
    <section className="bg-white border border-slate-200 rounded-2xl p-7 md:p-8"><div className="flex justify-between items-start gap-6 mb-7"><div><h2 className="text-[17px] font-semibold">Screening pipeline</h2><p className="text-[12px] text-slate-500 mt-1">{completed} of {stages.length} stages completed</p></div><StatusBadge tone={progress===100?'success':'info'}>{progress}% complete</StatusBadge></div><ProgressIndicator value={progress}/>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-5 mt-7">{stages.map(([label,done],index)=><div key={label}><span className={`w-7 h-7 rounded-full inline-flex items-center justify-center text-[11px] font-semibold ${done?'bg-emerald-50 text-emerald-700':'bg-slate-100 text-slate-500'}`}>{done?'✓':index+1}</span><p className="text-[11px] font-medium text-slate-700 mt-2">{label}</p><p className={`text-[10px] mt-1 ${done?'text-emerald-600':'text-slate-400'}`}>{done?'Completed':'Not started'}</p></div>)}</div>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-5 mt-9 pt-6 border-t border-slate-100"><div><p className="text-[13px] font-semibold text-slate-800">Continue screening</p><p className="text-[11px] text-slate-500 mt-1">{nextLabel}</p></div><button className="btn-primary" onClick={()=>navigate(`/projects/${state.projectId}/${next}`)}>{nextLabel}<ArrowRight size={14}/></button></div>
    </section></div>
}
