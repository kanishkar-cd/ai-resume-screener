import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import Layout from '@/components/layout/Layout'
import { PipelineProvider } from '@/store/pipelineStore'
import DocumentUpload from '@/pages/DocumentUpload'
import WeightageSetting from '@/pages/WeightageSetting'
import ResumeUpload from '@/pages/ResumeUpload'
import CandidateRanking from '@/pages/CandidateRanking'
import RecruiterDashboard from '@/pages/RecruiterDashboard'

function AppRoutes() {
  const location = useLocation()
  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route path="/"               element={<DocumentUpload />} />
        <Route path="/weightage"      element={<WeightageSetting />} />
        <Route path="/resume-upload"  element={<ResumeUpload />} />
        <Route path="/ranking"        element={<CandidateRanking />} />
        <Route path="/dashboard"      element={<RecruiterDashboard />} />
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
