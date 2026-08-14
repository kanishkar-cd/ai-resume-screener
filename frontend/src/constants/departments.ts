export interface Department {
  id: string
  code: string
  name: string
  description: string
  iconName: string
  activeRequisitions: number
  totalCandidates: number
  shortlistedCount: number
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
    activeRequisitions: 5,
    totalCandidates: 42,
    shortlistedCount: 12,
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
    activeRequisitions: 4,
    totalCandidates: 35,
    shortlistedCount: 10,
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
    activeRequisitions: 3,
    totalCandidates: 28,
    shortlistedCount: 8,
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
    activeRequisitions: 2,
    totalCandidates: 18,
    shortlistedCount: 5,
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
    activeRequisitions: 2,
    totalCandidates: 15,
    shortlistedCount: 4,
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
    activeRequisitions: 2,
    totalCandidates: 16,
    shortlistedCount: 4,
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
    activeRequisitions: 3,
    totalCandidates: 22,
    shortlistedCount: 6,
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
    activeRequisitions: 3,
    totalCandidates: 20,
    shortlistedCount: 5,
    badgeBg: 'bg-teal-50',
    badgeText: 'text-teal-700',
    accentColor: '#14b8a6',
  },
]
