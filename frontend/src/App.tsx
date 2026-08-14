import { BrowserRouter, Routes, Route, useLocation, Navigate } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import Layout from '@/components/layout/Layout'
import { PipelineProvider } from '@/store/pipelineStore'
import DocumentUpload from '@/pages/DocumentUpload'
import WeightageSetting from '@/pages/WeightageSetting'
import ResumeUpload from '@/pages/ResumeUpload'
import CandidateRanking from '@/pages/CandidateRanking'
import RecruiterDashboard from '@/pages/RecruiterDashboard'
import Dashboard from '@/pages/Dashboard'
import Projects from '@/pages/Projects'
import CreateProject from '@/pages/CreateProject'
import ProjectOverview from '@/pages/ProjectOverview'
import Processing from '@/pages/Processing'
import Reports from '@/pages/Reports'
import Departments from '@/pages/Departments'
import DepartmentDashboard from '@/pages/DepartmentDashboard'
import CreateRequisition from '@/pages/CreateRequisition'
import Shortlist from '@/pages/Shortlist'
import Assessment from '@/pages/Assessment'
import ProjectRoute from '@/components/layout/ProjectRoute'

function AppRoutes() {
  const location = useLocation()
  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/departments" element={<Departments />} />
        <Route path="/departments/:deptId" element={<DepartmentDashboard />} />
        <Route path="/departments/:deptId/requisitions/new" element={<CreateRequisition />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/new" element={<CreateProject />} />
        <Route path="/projects/:projectId" element={<ProjectRoute><ProjectOverview /></ProjectRoute>} />
        <Route path="/projects/:projectId/overview" element={<ProjectRoute><ProjectOverview /></ProjectRoute>} />
        <Route path="/projects/:projectId/job-description" element={<ProjectRoute><DocumentUpload /></ProjectRoute>} />
        <Route path="/projects/:projectId/resumes" element={<ProjectRoute><ResumeUpload /></ProjectRoute>} />
        <Route path="/projects/:projectId/weightage" element={<ProjectRoute><WeightageSetting /></ProjectRoute>} />
        <Route path="/projects/:projectId/processing" element={<ProjectRoute><Processing /></ProjectRoute>} />
        <Route path="/projects/:projectId/candidates" element={<ProjectRoute><RecruiterDashboard /></ProjectRoute>} />
        <Route path="/projects/:projectId/rankings" element={<ProjectRoute><CandidateRanking /></ProjectRoute>} />
        <Route path="/projects/:projectId/shortlist" element={<ProjectRoute><Shortlist /></ProjectRoute>} />
        <Route path="/projects/:projectId/assessment" element={<ProjectRoute><Assessment /></ProjectRoute>} />
        <Route path="/projects/:projectId/reports" element={<ProjectRoute><Reports /></ProjectRoute>} />
        <Route path="/settings" element={<div className="card p-8"><h1 className="text-xl font-bold">Settings</h1><p className="text-sm text-slate-500 mt-2">Application settings will appear here.</p></div>} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </AnimatePresence>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <PipelineProvider>
        <Layout>
          <AppRoutes />
        </Layout>
      </PipelineProvider>
    </BrowserRouter>
  )
}
