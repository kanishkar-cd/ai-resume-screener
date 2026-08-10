import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '@/api'
import { usePipeline } from '@/store/pipelineStore'

export default function CreateProject() {
  const [form, setForm] = useState({ title: '', target_role: '', department: '', description: '' })
  const [saving, setSaving] = useState(false); const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate(); const { dispatch } = usePipeline()
  const submit = async (e: React.FormEvent) => { e.preventDefault(); setSaving(true); setError(null); try { const project = await api.createProject({ title: form.title.trim(), target_role: form.target_role.trim(), department: form.department.trim() || null, description: form.description.trim() || null, status: 'DRAFT' }); dispatch({ type: 'SELECT_PROJECT', payload: project }); navigate(`/projects/${project.id}`) } catch (err) { setError(err instanceof ApiError ? err.message : 'Unable to create project.') } finally { setSaving(false) } }
  return <div className="max-w-3xl mx-auto"><button onClick={() => navigate('/projects')} className="text-[12px] text-slate-500 flex gap-1 items-center mb-4"><ArrowLeft size={13}/> Projects</button><div className="card p-6"><h1 className="text-[24px] font-bold text-slate-800">Create Project</h1><p className="text-[12px] text-slate-500 mt-1 mb-6">Create the top-level container for this screening campaign.</p><form onSubmit={submit} className="space-y-4">{[['Project Name *','title'],['Target Role *','target_role'],['Department','department']].map(([label,key]) => <label className="block" key={key}><span className="text-[12px] font-semibold text-slate-600">{label}</span><input required={key==='title'||key==='target_role'} minLength={key==='title'?3:key==='target_role'?2:undefined} value={form[key as keyof typeof form]} onChange={e=>setForm({...form,[key]:e.target.value})} className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2.5 text-[13px] outline-none focus:border-sky-400"/></label>)}<label className="block"><span className="text-[12px] font-semibold text-slate-600">Description</span><textarea value={form.description} onChange={e=>setForm({...form,description:e.target.value})} rows={4} className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2.5 text-[13px] outline-none focus:border-sky-400"/></label>{error&&<p className="text-[12px] text-red-500">{error}</p>}<button disabled={saving} className="btn-primary">{saving?'Creating…':'Create Project'}</button></form></div></div>
}
