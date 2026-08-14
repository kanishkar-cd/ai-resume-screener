import { useState, useEffect } from 'react'
import { LayoutDashboard, Settings, Building2, PanelLeftClose, PanelLeftOpen, ChevronDown, ChevronRight } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'

interface SidebarProps {
  collapsed?: boolean
  onToggleCollapse?: () => void
}

export default function Sidebar({ collapsed = false, onToggleCollapse }: SidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { dispatch } = usePipeline()
  const [departmentsExpanded, setDepartmentsExpanded] = useState(
    location.pathname.startsWith('/departments')
  )

  // Expand departments automatically if navigating to a department subpage
  useEffect(() => {
    if (location.pathname.startsWith('/departments')) {
      setDepartmentsExpanded(true)
    }
  }, [location.pathname])

  const handleDepartmentSubClick = (deptId: string) => {
    dispatch({ type: 'SET_DEPARTMENT_ID', payload: deptId })
    navigate(`/departments/${deptId}`)
  }

  const isDepartmentsActive = location.pathname === '/departments' || location.pathname.startsWith('/departments/')

  return (
    <aside
      className={`app-sidebar flex flex-col transition-all duration-300 ${
        collapsed ? 'w-16 p-2.5' : 'w-64 p-4'
      }`}
    >
      {/* Sidebar Header & Toggle */}
      <div className={`pb-4 border-b border-slate-100 flex items-center ${collapsed ? 'justify-center' : 'justify-between'}`}>
        {!collapsed && (
          <div className="cursor-pointer overflow-hidden" onClick={() => navigate('/dashboard')}>
            <p className="text-[13px] font-extrabold text-slate-900 truncate">AI Resume Screener</p>
            <p className="text-[10px] text-slate-400 font-semibold truncate">Recruiter Portal</p>
          </div>
        )}
        <button
          type="button"
          onClick={onToggleCollapse}
          title={collapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer shrink-0"
        >
          {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>
      </div>

      {/* Nav Items */}
      <nav className="py-4 space-y-1 flex-1 overflow-y-auto">
        {/* Dashboard Link */}
        <button
          type="button"
          title={collapsed ? 'Dashboard' : undefined}
          onClick={() => navigate('/dashboard')}
          className={`w-full flex items-center ${
            collapsed ? 'justify-center px-2 py-2.5' : 'gap-2.5 px-3 py-2.5'
          } rounded-lg text-[12px] font-semibold transition-all cursor-pointer ${
            location.pathname === '/dashboard'
              ? 'bg-blue-50 text-blue-700 font-bold'
              : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
          }`}
        >
          <LayoutDashboard size={16} className="shrink-0" />
          {!collapsed && <span className="truncate">Dashboard</span>}
        </button>

        {/* Expandable Departments Link */}
        <div>
          <div
            className={`w-full flex items-center justify-between ${
              collapsed ? 'px-2 py-2.5 justify-center' : 'px-3 py-2.5'
            } rounded-lg text-[12px] font-semibold transition-all cursor-pointer group ${
              isDepartmentsActive
                ? 'bg-blue-50/70 text-blue-700'
                : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
            }`}
          >
            <button
              type="button"
              title={collapsed ? 'Departments' : undefined}
              onClick={() => navigate('/departments')}
              className="flex items-center gap-2.5 flex-1 min-w-0 text-left"
            >
              <Building2 size={16} className="shrink-0" />
              {!collapsed && (
                <span className={`truncate ${location.pathname === '/departments' ? 'font-bold' : ''}`}>
                  Departments
                </span>
              )}
            </button>

            {!collapsed && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  setDepartmentsExpanded(!departmentsExpanded)
                }}
                className="p-1 rounded-md text-slate-400 hover:text-slate-700 hover:bg-slate-200/50 transition-colors shrink-0"
              >
                {departmentsExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
            )}
          </div>

          {/* Sub-departments List */}
          {!collapsed && departmentsExpanded && (
            <div className="pl-7 pr-1 py-1 space-y-0.5 mt-0.5 border-l-2 border-slate-100 ml-5">
              {DEPARTMENTS.map((dept) => {
                const isSubActive = location.pathname === `/departments/${dept.id}`
                return (
                  <button
                    key={dept.id}
                    type="button"
                    onClick={() => handleDepartmentSubClick(dept.id)}
                    className={`w-full text-left px-2.5 py-1.5 rounded-md text-[11px] font-medium transition-colors truncate block ${
                      isSubActive
                        ? 'bg-blue-100/70 text-blue-800 font-bold'
                        : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100/70'
                    }`}
                  >
                    {dept.name}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </nav>

      {/* Footer Settings */}
      <div className="mt-auto pt-3 border-t border-slate-100">
        <button
          type="button"
          title={collapsed ? 'Settings' : undefined}
          onClick={() => navigate('/settings')}
          className={`w-full flex items-center ${
            collapsed ? 'justify-center px-2 py-2.5' : 'gap-2.5 px-3 py-2.5'
          } rounded-lg text-[12px] font-semibold transition-all cursor-pointer ${
            location.pathname === '/settings'
              ? 'bg-blue-50 text-blue-700 font-bold'
              : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
          }`}
        >
          <Settings size={16} className="shrink-0" />
          {!collapsed && <span className="truncate">Settings</span>}
        </button>
      </div>
    </aside>
  )
}
