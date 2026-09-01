import { Candidate } from '@/types'

export interface MockRequisition {
  id: string
  deptId: string
  refCode: string
  title: string
  targetRole: string
  experienceLevel: 'Experienced' | 'Fresher'
  hiringManager: string
  candidateCount: number
  shortlistedCount: number
  status: 'ACTIVE' | 'DRAFT' | 'COMPLETED'
  createdAt: string
  passingScore: number
  weights: {
    skills: number
    projects: number
    education: number
    certifications: number
    languages: number
    experience: number
  }
}

export const MOCK_REQUISITIONS: MockRequisition[] = []
export const MOCK_CANDIDATES: Candidate[] = []
