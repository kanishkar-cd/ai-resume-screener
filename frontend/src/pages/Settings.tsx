import { useState } from 'react'
import {
  Sliders,
  Shield,
  Server,
  Database,
  CheckCircle2,
  Cpu,
  RefreshCw,
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'

export default function Settings() {
  const [activeTab, setActiveTab] = useState<'system' | 'departments' | 'pipeline'>('system')
  const [llmModel, setLlmModel] = useState('Gemini 1.5 Flash (Default)')
  const [strictThreshold, setStrictThreshold] = useState(70)
  const [savedSuccess, setSavedSuccess] = useState(false)

  const handleSave = () => {
    setSavedSuccess(true)
    setTimeout(() => setSavedSuccess(false), 3000)
  }

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-7">
      <div className="border-b border-slate-200/80 pb-5">
        <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight flex items-center gap-2.5">
          <Sliders size={24} className="text-blue-600" />
          Application Settings
        </h1>
        <p className="text-xs text-slate-500 mt-1 font-medium">
          Configure enterprise ATS screening parameters, AI evaluation thresholds, and department workflows.
        </p>
      </div>

      {savedSuccess && (
        <div className="p-3.5 bg-emerald-50 border border-emerald-200 rounded-xl flex items-center gap-2.5 text-xs text-emerald-800 font-semibold animate-fadeIn">
          <CheckCircle2 size={16} className="text-emerald-600 shrink-0" />
          Settings updated and persisted successfully.
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-200">
        <button
          type="button"
          onClick={() => setActiveTab('system')}
          className={`pb-3 px-4 text-xs font-bold border-b-2 transition-colors cursor-pointer ${
            activeTab === 'system'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          System & AI Engine
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('departments')}
          className={`pb-3 px-4 text-xs font-bold border-b-2 transition-colors cursor-pointer ${
            activeTab === 'departments'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          Department Configuration
        </button>
      </div>

      {activeTab === 'system' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white border border-slate-200/80 rounded-2xl p-6 space-y-5 shadow-xs">
            <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Cpu size={16} className="text-blue-600" />
              AI Scoring Engine
            </h2>
            <div className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-600 font-semibold mb-1.5">Default LLM Model</label>
                <select
                  value={llmModel}
                  onChange={(e) => setLlmModel(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-xs text-slate-800 font-medium focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                >
                  <option value="Gemini 1.5 Flash (Default)">Gemini 1.5 Flash (Fast, Recommended)</option>
                  <option value="Gemini 1.5 Pro">Gemini 1.5 Pro (Deep Analysis)</option>
                  <option value="Rule-based Heuristic Engine">Rule-based Heuristic Engine (Offline)</option>
                </select>
              </div>

              <div>
                <div className="flex justify-between items-center mb-1.5">
                  <label className="text-slate-600 font-semibold">Shortlist Score Cutoff Threshold</label>
                  <span className="font-bold text-blue-600">{strictThreshold}%</span>
                </div>
                <input
                  type="range"
                  min="50"
                  max="90"
                  value={strictThreshold}
                  onChange={(e) => setStrictThreshold(Number(e.target.value))}
                  className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                />
                <p className="text-[11px] text-slate-400 mt-1">
                  Candidates scoring at or above this threshold will automatically qualify for shortlisting.
                </p>
              </div>
            </div>
          </div>

          <div className="bg-white border border-slate-200/80 rounded-2xl p-6 space-y-5 shadow-xs">
            <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Server size={16} className="text-emerald-600" />
              Service Status & Infrastructure
            </h2>
            <div className="space-y-3 text-xs">
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-100">
                <div className="flex items-center gap-2.5">
                  <Database size={15} className="text-indigo-600" />
                  <div>
                    <p className="font-bold text-slate-800">PostgreSQL Database</p>
                    <p className="text-[10px] text-slate-400">Port 5432 · Connection Pool Active</p>
                  </div>
                </div>
                <span className="px-2.5 py-1 bg-emerald-100 text-emerald-700 text-[10px] font-bold rounded-full">
                  Online
                </span>
              </div>

              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-100">
                <div className="flex items-center gap-2.5">
                  <Shield size={15} className="text-blue-600" />
                  <div>
                    <p className="font-bold text-slate-800">FastAPI Backend API</p>
                    <p className="text-[10px] text-slate-400">Port 8000 · v1.0.0</p>
                  </div>
                </div>
                <span className="px-2.5 py-1 bg-emerald-100 text-emerald-700 text-[10px] font-bold rounded-full">
                  Healthy
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'departments' && (
        <div className="bg-white border border-slate-200/80 rounded-2xl p-6 space-y-4 shadow-xs">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-slate-900">Standard Organization Departments (8 Units)</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                All organizational requisitions strictly map to these 8 enterprise departments.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-2">
            {DEPARTMENTS.map((dept) => (
              <div
                key={dept.id}
                className="p-3.5 bg-slate-50 border border-slate-200/70 rounded-xl flex items-center justify-between"
              >
                <div>
                  <p className="text-xs font-bold text-slate-800">{dept.name}</p>
                  <p className="text-[10px] font-semibold text-slate-400">{dept.code}</p>
                </div>
                <span className="px-2 py-0.5 bg-blue-50 text-blue-600 text-[10px] font-bold rounded-md">
                  Active
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex justify-end gap-3 pt-4">
        <button
          type="button"
          onClick={handleSave}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold transition-all shadow-xs cursor-pointer flex items-center gap-2"
        >
          <RefreshCw size={14} />
          Save Configurations
        </button>
      </div>
    </div>
  )
}
