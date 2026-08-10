import { useEffect, useState } from 'react'
import { FileText, Users, Scale, Trophy, ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api'
import { usePipeline } from '@/store/pipelineStore'

export default function ProjectOverview() {
  const { state } = usePipeline(); const navigate = useNavigate()
  const [jd, setJd] = useState(false); const [resumeCount, setResumeCount] = useState(0); const [candidateCount, setCandidateCount] = useState(0)
  useEffect(() => { if (!state.projectId) return; api.getJobDescription(state.projectId).then(()=>setJd(true)).catch(()=>setJd(false)); api.listProjectResumes(state.projectId).then(r=>setResumeCount(r.total)).catch(()=>setResumeCount(0)); api.getProjectScores(state.projectId).then(r=>setCandidateCount(r.length)).catch(()=>setCandidateCount(0)) }, [state.projectId])
  if (!state.projectId) return null
  const cards = [{label:'Job Description',value:jd?'Uploaded':'Not uploaded',icon:FileText},{label:'Resumes',value:`${resumeCount} resumes`,icon:Users},{label:'Weightage',value:state.weightConfigSaved?'Configured':'Not configured',icon:Scale},{label:'Candidates',value:String(candidateCount),icon:Users},{label:'Ranking',value:state.scoringComplete?'Available':'Not available',icon:Trophy}]
  const stages = ['Project','Job Description','Weightage','Resumes','Processing','Scoring','Ranking']
  const completed = [true,jd,state.weightConfigSaved,resumeCount>0,state.jdNormalized,state.scoringComplete,state.completedSteps.includes(4)]
  const next = !jd ? 'job-description' : !state.weightConfigSaved ? 'weightage' : resumeCount===0 ? 'resumes' : 'processing'
  const nextLabel = !jd ? 'Upload Job Description' : !state.weightConfigSaved ? 'Configure Weightage' : resumeCount===0 ? 'Upload Resumes' : 'View Processing'
  return <div className="max-w-5xl mx-auto"><h2 className="text-[20px] font-bold text-slate-800 mb-4">Project Overview</h2><div className="grid md:grid-cols-5 gap-3">{cards.map(c=><div className="card p-4" key={c.label}><c.icon size={16} className="text-sky-600 mb-3"/><p className="text-[10px] uppercase font-bold text-slate-400">{c.label}</p><p className="text-[13px] font-semibold text-slate-700 mt-1">{c.value}</p></div>)}</div><div className="card p-5 mt-4"><div className="flex justify-between items-center mb-4"><h3 className="font-bold text-slate-800">Pipeline Progress</h3><button className="btn-primary" onClick={()=>navigate(`/projects/${state.projectId}/${next}`)}>{nextLabel}<ArrowRight size={14}/></button></div><div className="grid md:grid-cols-7 gap-2">{stages.map((stage,i)=><div className={`rounded-lg p-3 border ${completed[i]?'bg-green-50 border-green-200':'bg-slate-50 border-slate-100'}`} key={stage}><span className="text-[10px] font-bold text-slate-400">{i+1}</span><p className="text-[11px] font-semibold text-slate-700 mt-1">{stage}</p><p className={`text-[9px] mt-1 ${completed[i]?'text-green-600':'text-slate-400'}`}>{completed[i]?'Completed':'Not Started'}</p></div>)}</div></div></div>
}
