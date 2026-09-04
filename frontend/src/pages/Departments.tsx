import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Cpu,
  LayoutGrid,
  Sparkles,
  TrendingUp,
  Shield,
  Users,
  Briefcase,
  CheckCircle2,
  ArrowRight,
  Search,
  Building2,
  AlertCircle,
  ChevronRight,
  FolderKanban,
} from 'lucide-react'
import { DEPARTMENTS, Department } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api, Project } from '@/api'

const ICON_MAP: Record<string, any> = {
  Cpu,
  LayoutGrid,
  Sparkles,
  TrendingUp,
  Shield,
  Users,
  Briefcase,
  CheckCircle2,
}

export default function Departments() {
  const navigate = useNavigate()
  const { dispatch } = usePipeline()
  const [searchTerm, setSearchTerm] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api.listProjects()
      .then((res) => {
        if (active) {
          setProjects(res.items || [])
          setError(null)
        }
      })
      .catch((err) => {
        if (active) {
          setError(err instanceof Error ? err.message : 'Unable to connect to backend service')
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const handleOpenDepartment = (dept: Department) => {
    dispatch({ type: 'SET_DEPARTMENT_ID', payload: dept.id })
    navigate(`/dashboard?dept=${encodeURIComponent(dept.name)}`)
  }

  const filteredDepartments = useMemo(() => {
    return DEPARTMENTS.filter(
      (d) =>
        d.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        d.code.toLowerCase().includes(searchTerm.toLowerCase()) ||
        d.description.toLowerCase().includes(searchTerm.toLowerCase())
    )
  }, [searchTerm])

  // Calculate per-department project metrics and latest updated date from backend data
  const departmentMetrics = useMemo(() => {
    const map = new Map<string, { count: number; lastUpdated: string | null }>()
    for (const d of DEPARTMENTS) {
      const deptProjects = projects.filter((p) => p.department === d.name)
      let latest: string | null = null
      if (deptProjects.length > 0) {
        const sorted = [...deptProjects].sort(
          (a, b) =>
            new Date(b.updated_at || b.created_at).getTime() -
            new Date(a.updated_at || a.created_at).getTime()
        )
        latest = sorted[0].updated_at || sorted[0].created_at
      }
      map.set(d.id, { count: deptProjects.length, lastUpdated: latest })
    }
    return map
  }, [projects])

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-7">
      {/* Clean ATS Navigation & Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200/60 pb-6">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-400 mb-1">
            <button
              type="button"
              onClick={() => navigate('/dashboard')}
              className="hover:text-blue-600 transition-colors cursor-pointer"
            >
              Overview
            </button>
            <ChevronRight size={12} />
            <span className="text-slate-700 font-bold">Departments</span>
          </div>
          <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight flex items-center gap-2.5">
            <Building2 size={24} className="text-blue-600" />
            Department Directory
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl font-medium">
            Manage organization hiring pipelines across the 8 company departments. Select a department to manage active requisitions and candidates.
          </p>
        </div>

        {/* Minimal Global Stats Summary */}
        <div className="flex items-center gap-3 bg-white border border-slate-200/80 rounded-2xl p-2.5 px-4 shadow-sm self-stretch md:self-auto justify-around">
          <div className="flex items-center gap-2.5 pr-4 border-r border-slate-100">
            <div className="w-8 h-8 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold text-xs">
              {DEPARTMENTS.length}
            </div>
            <div>
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Departments</p>
              <p className="text-xs font-bold text-slate-800">Active Units</p>
            </div>
          </div>

          <div className="flex items-center gap-2.5 pl-2">
            <div className="w-8 h-8 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center font-bold text-xs">
              {loading ? '...' : projects.length}
            </div>
            <div>
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Total Reqs</p>
              <p className="text-xs font-bold text-slate-800">Database Records</p>
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50/80 border border-red-200/80 rounded-2xl flex items-center gap-3 text-red-700 text-xs font-semibold">
          <AlertCircle size={16} className="shrink-0" />
          <div>
            <p className="font-bold">Backend Communication Notice</p>
            <p className="text-[11px] font-normal text-red-600 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Refined Search Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search by department name or code (e.g., Software Engineering, SWE, QA)..."
            className="w-full pl-10 pr-4 py-2 bg-white border border-slate-200/90 rounded-xl text-xs font-medium text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all placeholder:text-slate-400"
          />
        </div>
        <div className="text-xs font-medium text-slate-400">
          Showing <span className="font-bold text-slate-700">{filteredDepartments.length}</span> of {DEPARTMENTS.length} departments
        </div>
      </div>

      {/* Modern Department Cards Grid (4-column x 2-row) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
        {filteredDepartments.map((dept) => {
          const Icon = ICON_MAP[dept.iconName] || Building2
          const metrics = departmentMetrics.get(dept.id) || { count: 0, lastUpdated: null }
          const activeCount = metrics.count

          return (
            <div
              key={dept.id}
              onClick={() => handleOpenDepartment(dept)}
              className="group bg-white border border-slate-200/80 rounded-2xl p-5 shadow-xs hover:shadow-md hover:border-blue-300/80 transition-all cursor-pointer flex flex-col justify-between"
            >
              <div className="space-y-3">
                {/* Header Icon */}
                <div className="flex items-center justify-between">
                  <div className={`p-2.5 rounded-xl ${dept.badgeBg} transition-transform group-hover:scale-105`}>
                    <Icon size={18} className={dept.badgeText} />
                  </div>
                </div>

                {/* Title & Description */}
                <div>
                  <h3 className="text-sm font-bold text-slate-900 group-hover:text-blue-600 transition-colors">
                    {dept.name}
                  </h3>
                  <p className="text-[11px] text-slate-500 mt-1 line-clamp-2 leading-relaxed font-normal">
                    {dept.description}
                  </p>
                </div>
              </div>

              {/* Bottom Metrics & Action */}
              <div className="mt-5 pt-4 border-t border-slate-100/80 space-y-3">
                <div className="flex items-center text-xs">
                  <div className="flex items-center gap-1.5 text-slate-500">
                    <FolderKanban size={13} className="text-blue-500" />
                    <span className="font-semibold text-slate-700">
                      {loading ? '...' : activeCount}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      {activeCount === 1 ? 'requisition' : 'requisitions'}
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleOpenDepartment(dept)
                  }}
                  className="w-full flex items-center justify-center gap-1.5 py-2 px-3 bg-slate-50 group-hover:bg-blue-600 text-slate-700 group-hover:text-white rounded-xl text-xs font-semibold transition-all border border-slate-200/70 group-hover:border-transparent cursor-pointer"
                >
                  <span>Open Department</span>
                  <ArrowRight size={13} className="group-hover:translate-x-0.5 transition-transform" />
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
