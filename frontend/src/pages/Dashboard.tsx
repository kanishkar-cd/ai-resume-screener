import { Briefcase, FolderPlus, LayoutDashboard } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

export default function Dashboard() {
  const navigate = useNavigate()
  return <div className="max-w-5xl mx-auto">
    <div className="mb-6"><h1 className="text-[26px] font-bold text-slate-800">Dashboard</h1><p className="text-[13px] text-slate-500 mt-1">Manage hiring projects and launch project-scoped screening workflows.</p></div>
    <div className="grid md:grid-cols-2 gap-4">
      <button onClick={() => navigate('/projects')} className="card p-6 text-left hover:border-sky-300 transition-colors"><LayoutDashboard className="text-sky-600 mb-3"/><h2 className="font-bold text-slate-800">View Projects</h2><p className="text-[12px] text-slate-500 mt-1">Open an existing campaign and continue its pipeline.</p></button>
      <button onClick={() => navigate('/projects/new')} className="card p-6 text-left hover:border-sky-300 transition-colors"><FolderPlus className="text-sky-600 mb-3"/><h2 className="font-bold text-slate-800">Create Project</h2><p className="text-[12px] text-slate-500 mt-1">Start a separate screening campaign with isolated data.</p></button>
    </div>
    <div className="card p-6 mt-4 flex items-center gap-4"><Briefcase className="text-slate-400"/><div><p className="font-semibold text-slate-700">Project-first screening</p><p className="text-[12px] text-slate-500">Every JD, resume, weight configuration, score, and ranking belongs to one selected project.</p></div></div>
  </div>
}
