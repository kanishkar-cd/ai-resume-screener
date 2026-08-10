import { LayoutDashboard, FolderKanban, Settings, FileText, FolderUp, Scale, Activity, Users, ListOrdered, BarChart3 } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { usePipeline } from '@/store/pipelineStore'

export default function Sidebar() {
  const navigate=useNavigate(); const location=useLocation(); const { state }=usePipeline()
  const global=[['Dashboard','/dashboard',LayoutDashboard],['Projects','/projects',FolderKanban]] as const
  const projectId=state.projectId
  const scoped=projectId ? [
    ['Overview',`/projects/${projectId}`,LayoutDashboard],['Job Description',`/projects/${projectId}/job-description`,FileText],['Resumes',`/projects/${projectId}/resumes`,FolderUp],['Weightage',`/projects/${projectId}/weightage`,Scale],['Processing',`/projects/${projectId}/processing`,Activity],['Candidates',`/projects/${projectId}/candidates`,Users],['Rankings',`/projects/${projectId}/rankings`,ListOrdered],['Reports',`/projects/${projectId}/reports`,BarChart3],
  ] as const : []
  const item=(label:string,path:string,Icon:typeof LayoutDashboard)=><button key={path} type="button" onClick={()=>navigate(path)} className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-[12px] font-semibold transition-colors ${location.pathname===path?'bg-sky-600 text-white':'text-slate-600 hover:bg-sky-50 hover:text-sky-700'}`}><Icon size={15}/>{label}</button>
  return <aside className="app-sidebar glow-border-sky p-4 flex flex-col"><div className="pb-4 border-b border-slate-100"><p className="text-[14px] font-extrabold text-slate-800">AI Resume Screener</p><p className="text-[10px] text-sky-600 font-semibold">Recruiter Workspace</p></div><nav className="py-4 space-y-1">{global.map(([label,path,Icon])=>item(label,path,Icon))}</nav>{projectId&&<><p className="text-[9px] uppercase tracking-widest font-bold text-slate-400 px-3 py-2 border-t border-slate-100">Current Project</p><nav className="space-y-1">{scoped.map(([label,path,Icon])=>item(label,path,Icon))}</nav></>}<div className="mt-auto pt-3 border-t border-slate-100">{item('Settings','/settings',Settings)}</div></aside>
}
