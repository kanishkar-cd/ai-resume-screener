export interface Department {
  id: string
  code: string
  name: string
  description: string
  iconName: string
  badgeBg: string
  badgeText: string
  accentColor: string
}

export const DEPARTMENTS: Department[] = [
  {
    id: 'software-engineering',
    code: 'SOFTWARE_ENGINEERING',
    name: 'Software Engineering',
    description: 'Full-stack development, cloud architecture, microservices, and core platform development.',
    iconName: 'Cpu',
    badgeBg: 'bg-blue-50',
    badgeText: 'text-blue-700',
    accentColor: '#3b82f6',
  },
  {
    id: 'data-engineering',
    code: 'DATA_ENGINEERING',
    name: 'Data Engineering',
    description: 'ETL pipelines, data warehousing, machine learning infrastructure, and analytics engines.',
    iconName: 'Sparkles',
    badgeBg: 'bg-indigo-50',
    badgeText: 'text-indigo-700',
    accentColor: '#6366f1',
  },
  {
    id: 'pmo',
    code: 'PMO',
    name: 'PMO',
    description: 'Program management office, agile delivery, technical project governance, and release management.',
    iconName: 'LayoutGrid',
    badgeBg: 'bg-purple-50',
    badgeText: 'text-purple-700',
    accentColor: '#8b5cf6',
  },
  {
    id: 'qa',
    code: 'QA',
    name: 'QA',
    description: 'Quality assurance, automated testing frameworks, performance testing, and release validation.',
    iconName: 'CheckCircle2',
    badgeBg: 'bg-emerald-50',
    badgeText: 'text-emerald-700',
    accentColor: '#10b981',
  },
  {
    id: 'sysops',
    code: 'SYSOPS',
    name: 'SysOps',
    description: 'System administration, server infrastructure management, Linux systems, and hardware ops.',
    iconName: 'Briefcase',
    badgeBg: 'bg-amber-50',
    badgeText: 'text-amber-700',
    accentColor: '#f59e0b',
  },
  {
    id: 'itops',
    code: 'ITOPS',
    name: 'ITOps',
    description: 'IT service delivery, corporate infrastructure, network administration, and IT helpdesk management.',
    iconName: 'Users',
    badgeBg: 'bg-cyan-50',
    badgeText: 'text-cyan-700',
    accentColor: '#06b6d4',
  },
  {
    id: 'secops',
    code: 'SECOPS',
    name: 'SecOps',
    description: 'Cybersecurity engineering, threat detection, vulnerability management, and SOC operations.',
    iconName: 'Shield',
    badgeBg: 'bg-rose-50',
    badgeText: 'text-rose-700',
    accentColor: '#f43f5e',
  },
  {
    id: 'sre',
    code: 'SRE',
    name: 'SRE',
    description: 'Site reliability engineering, observability, fault tolerance, and SLO/SLI infrastructure.',
    iconName: 'TrendingUp',
    badgeBg: 'bg-teal-50',
    badgeText: 'text-teal-700',
    accentColor: '#14b8a6',
  },
]
