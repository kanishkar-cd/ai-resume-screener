import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import Layout from '@/components/layout/Layout'
import { PipelineProvider } from '@/store/pipelineStore'
import { DEPARTMENTS } from '@/constants/departments'
import ResumeUpload from '@/pages/ResumeUpload'
import CandidateRanking from '@/pages/CandidateRanking'
import Dashboard from '@/pages/Dashboard'
import Departments from '@/pages/Departments'
import CreateRequisition from '@/pages/CreateRequisition'
import Shortlist from '@/pages/Shortlist'
import Assessment from '@/pages/Assessment'
import Settings from '@/pages/Settings'
import ProjectRoute from '@/components/layout/ProjectRoute'

function DepartmentRedirect() {
  const { deptId } = useParams<{ deptId: string }>()
  const dept = DEPARTMENTS.find(
    (d) =>
      d.id.toLowerCase() === deptId?.toLowerCase() ||
      d.name.toLowerCase() === deptId?.toLowerCase() ||
      d.code.toLowerCase() === deptId?.toLowerCase()
  )
  const deptName = dept?.name || deptId || 'ALL'
  return <Navigate to={`/dashboard?dept=${encodeURIComponent(deptName)}`} replace />
}

function ProjectRootRedirect() {
  const { projectId } = useParams<{ projectId: string }>()
  return <Navigate to={`/projects/${projectId}/rankings`} replace />
}

function ProjectCandidatesRedirect() {
  const { projectId } = useParams<{ projectId: string }>()
  return <Navigate to={`/projects/${projectId}/rankings`} replace />
}

function ProjectReportsRedirect() {
  const { projectId } = useParams<{ projectId: string }>()
  return <Navigate to={`/projects/${projectId}/assessment`} replace />
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/departments" element={<Departments />} />
      <Route path="/departments/:deptId" element={<DepartmentRedirect />} />
      <Route path="/departments/:deptId/requisitions/new" element={<CreateRequisition />} />
      <Route path="/projects" element={<Navigate to="/dashboard" replace />} />
      <Route path="/projects/new" element={<CreateRequisition />} />
      <Route path="/projects/:projectId" element={<ProjectRootRedirect />} />
      <Route path="/projects/:projectId/overview" element={<ProjectRootRedirect />} />
      <Route path="/projects/:projectId/job-description" element={<ProjectRootRedirect />} />
      <Route path="/projects/:projectId/resumes" element={<ProjectRoute><ResumeUpload /></ProjectRoute>} />
      <Route path="/projects/:projectId/candidates" element={<ProjectCandidatesRedirect />} />
      <Route path="/projects/:projectId/rankings" element={<ProjectRoute><CandidateRanking /></ProjectRoute>} />
      <Route path="/projects/:projectId/shortlist" element={<ProjectRoute><Shortlist /></ProjectRoute>} />
      <Route path="/projects/:projectId/assessment" element={<ProjectRoute><Assessment /></ProjectRoute>} />
      <Route path="/projects/:projectId/reports" element={<ProjectReportsRedirect />} />
      <Route path="/settings" element={<Settings />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter
      future={{
        v7_startTransition: true,
        v7_relativeSplatPath: true,
      }}
    >
      <PipelineProvider>
        <Layout>
          <AppRoutes />
        </Layout>
      </PipelineProvider>
    </BrowserRouter>
  )
}

