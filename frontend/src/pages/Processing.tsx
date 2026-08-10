import { FileText, Users, Database, WandSparkles } from 'lucide-react'
import { usePipeline } from '@/store/pipelineStore'

export default function Processing() {
  const { state } = usePipeline()
  const normalized = Object.values(state.resumeProcessing).filter(r=>r.normalized).length
  const failed = Object.values(state.resumeProcessing).filter(r=>r.phase==='failed').length
  const cards=[{label:'JD Processing',value:state.jdNormalized?'Completed':state.jdProcessingStage||'Not Started',icon:FileText},{label:'Resume Processing',value:`${normalized}/${state.resumeDocumentIds.length} normalized`,icon:Users},{label:'Extraction',value:state.jdProcessingStage==='EXTRACTION'?'In Progress':state.jdNormalized?'Completed':'Not Started',icon:Database},{label:'Normalization',value:failed?`${failed} failed`:state.jdNormalized?'Active':'Not Started',icon:WandSparkles}]
  return <div className="max-w-5xl mx-auto"><h2 className="text-[20px] font-bold text-slate-800">Processing</h2><p className="text-[12px] text-slate-500 mt-1 mb-4">Live state from the existing document processing workflow.</p><div className="grid md:grid-cols-4 gap-3">{cards.map(c=><div className="card p-5" key={c.label}><c.icon className="text-sky-600 mb-3"/><p className="text-[11px] font-bold text-slate-500">{c.label}</p><p className="text-[13px] text-slate-700 mt-2">{c.value}</p></div>)}</div></div>
}
