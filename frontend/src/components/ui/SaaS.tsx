import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export function PageHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <div className="page-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action && <div className="page-heading-action">{action}</div>}</div>
}

export function StatCard({ label, value, icon: Icon, hint }: { label: string; value: ReactNode; icon?: LucideIcon; hint?: string }) {
  return <div className="stat-card">{Icon && <Icon size={17}/>}<p>{label}</p><strong>{value}</strong>{hint && <span>{hint}</span>}</div>
}

export function EmptyState({ icon: Icon, title, description, action }: { icon: LucideIcon; title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><span><Icon size={22}/></span><h3>{title}</h3><p>{description}</p>{action}</div>
}

export function StatusBadge({ children, tone='neutral' }: { children: ReactNode; tone?: 'neutral'|'info'|'success'|'warning'|'danger' }) {
  return <span className={`saas-status ${tone}`}>{children}</span>
}

export function ProgressIndicator({ value }: { value: number }) {
  return <div className="saas-progress"><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }}/></div>
}

export function Skeleton({ className='' }: { className?: string }) {
  return <div className={`saas-skeleton ${className}`}/>
}
