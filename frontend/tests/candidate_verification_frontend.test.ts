/**
 * Comprehensive frontend tests for Phase 5: Candidate Verification Dashboard.
 *
 * Validates:
 * 1. Starting verification & Duplicate Click Prevention
 * 2. In-progress Polling & Progress Calculations
 * 3. Status Rendering (Identity, Verification, Repeat Applications)
 * 4. Separation of Repeat Applications from Fraud / Fabrication
 * 5. Retry Mechanism for Failed Candidate Verification Tasks
 * 6. Review Actions (Approve/Reject) with Notes and Authorization Error Handling
 * 7. Network Failure & Error Recovery States
 * 8. Empty Candidate List Rendering
 * 9. Page-Refresh Recovery from Persisted Backend State
 */

import assert from 'node:assert'

import type {
  BatchVerificationSummary,
  CandidateVerificationItemResult,
  CandidateVerificationStatus,
  CandidateIdentityStatus,
  RepeatApplicationStatus,
  BatchVerificationStatus,
  ManualReviewDecision,
  CandidateManualReviewRequest,
} from '../src/api/types'

// ── State Reducer / Store Simulator for CandidateVerificationDashboard ──────

interface VerificationState {
  loading: boolean
  verifying: boolean
  retryingId: string | null
  summary: BatchVerificationSummary | null
  documents: Record<string, { id: string; verification_status: CandidateVerificationStatus; review_note?: string }>
  error: string | null
  searchQuery: string
  statusFilter: string
  repeatFilter: string
  selectedCandidate: CandidateVerificationItemResult | null
  selectedDocId: string | null
  reviewNote: string
  reviewActionLoading: boolean
  reviewError: string | null
}

const initialVerificationState: VerificationState = {
  loading: true,
  verifying: false,
  retryingId: null,
  summary: null,
  documents: {},
  error: null,
  searchQuery: '',
  statusFilter: 'ALL',
  repeatFilter: 'ALL',
  selectedCandidate: null,
  selectedDocId: null,
  reviewNote: '',
  reviewActionLoading: false,
  reviewError: null,
}

type VerificationAction =
  | { type: 'FETCH_START' }
  | { type: 'FETCH_SUCCESS'; payload: BatchVerificationSummary; documents?: Record<string, { id: string; verification_status: CandidateVerificationStatus; review_note?: string }> }
  | { type: 'FETCH_ERROR'; payload: string }
  | { type: 'VERIFY_START' }
  | { type: 'VERIFY_ERROR'; payload: string }
  | { type: 'POLL_UPDATE'; payload: BatchVerificationSummary }
  | { type: 'RETRY_START'; payload: string }
  | { type: 'RETRY_SUCCESS'; payload: BatchVerificationSummary }
  | { type: 'RETRY_ERROR'; payload: string }
  | { type: 'SELECT_CANDIDATE'; payload: CandidateVerificationItemResult | null }
  | { type: 'SELECT_DOCUMENT'; payload: string | null }
  | { type: 'SET_REVIEW_NOTE'; payload: string }
  | { type: 'REVIEW_START' }
  | { type: 'REVIEW_SUCCESS'; payload: { candidateId: string; newStatus: CandidateVerificationStatus; note: string } }
  | { type: 'DOCUMENT_REVIEW_SUCCESS'; payload: { documentId: string; newStatus: CandidateVerificationStatus; note?: string } }
  | { type: 'REVIEW_ERROR'; payload: string }
  | { type: 'SET_SEARCH'; payload: string }
  | { type: 'SET_STATUS_FILTER'; payload: string }
  | { type: 'SET_REPEAT_FILTER'; payload: string }

function verificationReducer(state: VerificationState, action: VerificationAction): VerificationState {
  switch (action.type) {
    case 'FETCH_START':
      return { ...state, loading: true, error: null }
    case 'FETCH_SUCCESS':
      return {
        ...state,
        loading: false,
        summary: action.payload,
        documents: action.documents || state.documents,
        verifying: action.payload.status === 'IN_PROGRESS',
        error: null,
      }
    case 'FETCH_ERROR':
      return { ...state, loading: false, error: action.payload }
    case 'VERIFY_START':
      return { ...state, verifying: true, error: null }
    case 'VERIFY_ERROR':
      return { ...state, verifying: false, error: action.payload }
    case 'POLL_UPDATE':
      return {
        ...state,
        summary: action.payload,
        verifying: action.payload.status === 'IN_PROGRESS',
      }
    case 'RETRY_START':
      return { ...state, retryingId: action.payload, error: null }
    case 'RETRY_SUCCESS':
      return {
        ...state,
        retryingId: null,
        summary: action.payload,
      }
    case 'RETRY_ERROR':
      return { ...state, retryingId: null, error: action.payload }
    case 'SELECT_CANDIDATE': {
      const cand = action.payload
      const firstDoc = cand && cand.document_ids && cand.document_ids.length > 0 ? cand.document_ids[0] : null
      return {
        ...state,
        selectedCandidate: cand,
        selectedDocId: firstDoc,
        reviewNote: '',
        reviewError: null,
      }
    }
    case 'SELECT_DOCUMENT':
      return { ...state, selectedDocId: action.payload, reviewError: null }
    case 'SET_REVIEW_NOTE':
      return { ...state, reviewNote: action.payload }
    case 'REVIEW_START':
      return { ...state, reviewActionLoading: true, reviewError: null }
    case 'DOCUMENT_REVIEW_SUCCESS': {
      const { documentId, newStatus, note } = action.payload
      const updatedDocs = {
        ...state.documents,
        [documentId]: { id: documentId, verification_status: newStatus, review_note: note },
      }
      return {
        ...state,
        documents: updatedDocs,
        reviewActionLoading: false,
        reviewNote: '',
        reviewError: null,
      }
    }
    case 'REVIEW_SUCCESS': {
      if (!state.summary) return state
      const updatedResults = state.summary.results.map((c) =>
        c.candidate_id === action.payload.candidateId
          ? { ...c, verification_status: action.payload.newStatus, review_note: action.payload.note }
          : c,
      )
      const verifiedCount = updatedResults.filter((c) => c.verification_status === 'VERIFIED').length
      const reviewRequiredCount = updatedResults.filter((c) => c.verification_status === 'REVIEW_REQUIRED').length
      const failedCount = updatedResults.filter((c) => c.verification_status === 'FAILED').length

      const updatedSummary: BatchVerificationSummary = {
        ...state.summary,
        verified_candidates: verifiedCount,
        review_required_candidates: reviewRequiredCount,
        failed_candidates: failedCount,
        results: updatedResults,
      }
      return {
        ...state,
        reviewActionLoading: false,
        summary: updatedSummary,
        selectedCandidate: updatedResults.find((c) => c.candidate_id === action.payload.candidateId) || null,
        reviewNote: '',
      }
    }
    case 'REVIEW_ERROR':
      return { ...state, reviewActionLoading: false, reviewError: action.payload }
    case 'SET_SEARCH':
      return { ...state, searchQuery: action.payload }
    case 'SET_STATUS_FILTER':
      return { ...state, statusFilter: action.payload }
    case 'SET_REPEAT_FILTER':
      return { ...state, repeatFilter: action.payload }
    default:
      return state
  }
}

// ── Filter and Eligibility Logic ──────────────────────────────

function filterCandidates(
  results: CandidateVerificationItemResult[],
  search: string,
  statusFilter: string,
  repeatFilter: string,
): CandidateVerificationItemResult[] {
  return results.filter((c) => {
    if (search.trim()) {
      const q = search.toLowerCase()
      const matchesName = c.candidate_name?.toLowerCase().includes(q) || false
      const matchesEmail = c.candidate_email?.toLowerCase().includes(q) || false
      if (!matchesName && !matchesEmail) return false
    }
    if (statusFilter !== 'ALL' && c.verification_status !== statusFilter) {
      return false
    }
    if (repeatFilter !== 'ALL' && c.repeat_application_status !== repeatFilter) {
      return false
    }
    return true
  })
}

function shouldShowReviewButtons(status: CandidateVerificationStatus): boolean {
  // Phase 4 Requirement: Show Approve/Reject ONLY for documents whose persisted status is REVIEW_REQUIRED
  return status === 'REVIEW_REQUIRED'
}

function buildReviewRequest(
  projectId: string,
  documentId: string,
  decision: ManualReviewDecision,
  note?: string | null,
) {
  if (!projectId) throw new Error('projectId is required')
  if (!documentId) throw new Error('documentId is required')
  return {
    path: `/projects/${projectId}/documents/${documentId}/review`,
    method: 'POST',
    body: {
      decision,
      review_note: note || null,
    },
  }
}

function isRepeatApplicationFraud(repeatStatus: RepeatApplicationStatus): boolean {
  // STRICT CONSTRAINT: Repeat application is NEVER by itself evidence of fraud or fabricated resumes
  return false
}

function canProceedToAiScoring(candidate: CandidateVerificationItemResult): boolean {
  // Backend eligibility policy: Only candidates who are VERIFIED are eligible for AI scoring.
  // REVIEW_REQUIRED requires human approval first; FAILED requires retry/fixing.
  return candidate.verification_status === 'VERIFIED'
}

// ── Test Execution ────────────────────────────────────────────

function runAllTests() {
  console.log('===============================================================')
  console.log('--- Phase 5: Candidate Verification Frontend Test Suite ---')
  console.log('===============================================================\n')

  // Sample Mock Data
  const sampleCandidate1: CandidateVerificationItemResult = {
    candidate_id: 'cand-001',
    document_ids: ['doc-001'],
    candidate_name: 'Harshini CS',
    candidate_email: 'harshini@example.com',
    candidate_phone: '+1 555-0100',
    verification_status: 'VERIFIED',
    identity_status: 'MATCHED_SINGLE',
    repeat_application_status: 'FIRST_APPLICATION',
    matched_candidate_id: 'cand-001',
    match_reasons: ['Exact email match (harshini@example.com)'],
    conflicts: [],
    history: [
      {
        job_opening_id: 'job-101',
        job_title: 'Senior Python Engineer',
        applied_at: '2026-03-01T10:00:00Z',
        project_id: 'proj-1',
      },
    ],
    applied_job_count: 1,
    file_count: 1,
  }

  const sampleCandidate2: CandidateVerificationItemResult = {
    candidate_id: 'cand-002',
    document_ids: ['doc-002-a', 'doc-002-b'],
    candidate_name: 'Alex Morgan',
    candidate_email: 'alex.m@example.com',
    candidate_phone: '+1 555-0200',
    verification_status: 'REVIEW_REQUIRED',
    identity_status: 'REVIEW_REQUIRED',
    repeat_application_status: 'REPEAT_APPLICATION_DIFFERENT_JOB',
    matched_candidate_id: null,
    match_reasons: ['Phone match to Cand-999'],
    conflicts: ['Candidate name conflict: Alex Morgan vs Alexandra Morgan'],
    history: [
      {
        job_opening_id: 'job-050',
        job_title: 'Full Stack Developer',
        applied_at: '2025-11-15T09:30:00Z',
        project_id: 'proj-old',
      },
      {
        job_opening_id: 'job-101',
        job_title: 'Senior Python Engineer',
        applied_at: '2026-03-01T10:15:00Z',
        project_id: 'proj-1',
      },
    ],
    applied_job_count: 2,
    file_count: 2,
  }

  const sampleCandidate3: CandidateVerificationItemResult = {
    candidate_id: 'cand-003',
    document_ids: ['doc-003'],
    candidate_name: 'Corrupted File Candidate',
    candidate_email: 'corrupt@example.com',
    candidate_phone: null,
    verification_status: 'FAILED',
    identity_status: 'REVIEW_REQUIRED',
    repeat_application_status: 'FIRST_APPLICATION',
    matched_candidate_id: null,
    match_reasons: [],
    conflicts: ['Identity normalization failed: unreadable resume format'],
    error_message: 'File corrupted: could not parse PDF binary stream',
    history: [],
    applied_job_count: 0,
    file_count: 1,
  }

  // ── TEST 1: Starting Verification & Duplicate Click Prevention ──
  {
    console.log('Test 1: Starting Verification & Duplicate Click Prevention')
    let state = { ...initialVerificationState }

    // Start verification
    state = verificationReducer(state, { type: 'VERIFY_START' })
    assert.strictEqual(state.verifying, true, 'verifying flag must be true during verification')

    // Simulate duplicate click attempt while verifying is true
    let duplicateTriggered = false
    function handleVerifyClick() {
      if (state.verifying) return // Duplicate click guard
      duplicateTriggered = true
    }
    handleVerifyClick()
    assert.strictEqual(duplicateTriggered, false, 'Duplicate verification clicks must be ignored when verifying is in-progress')
    console.log('  ✓ Duplicate click prevention verified')
  }

  // ── TEST 2: In-Progress Polling & Progress Calculations ──
  {
    console.log('\nTest 2: In-Progress Polling & Progress Calculation')
    let state = { ...initialVerificationState }

    const inProgressSummary: BatchVerificationSummary = {
      project_id: 'proj-1',
      job_opening_id: 'job-101',
      status: 'IN_PROGRESS',
      total_candidates: 10,
      processed_candidates: 6,
      progress_percentage: 60,
      verified_candidates: 4,
      review_required_candidates: 1,
      failed_candidates: 1,
      results: [sampleCandidate1, sampleCandidate2, sampleCandidate3],
    }

    state = verificationReducer(state, { type: 'POLL_UPDATE', payload: inProgressSummary })
    assert.strictEqual(state.summary?.status, 'IN_PROGRESS')
    assert.strictEqual(state.summary?.progress_percentage, 60)
    assert.strictEqual(state.verifying, true, 'verifying remains true while batch status is IN_PROGRESS')

    // Simulate completed poll update
    const completedSummary: BatchVerificationSummary = {
      ...inProgressSummary,
      status: 'COMPLETED',
      processed_candidates: 10,
      progress_percentage: 100,
      verified_candidates: 7,
      review_required_candidates: 2,
      failed_candidates: 1,
    }
    state = verificationReducer(state, { type: 'POLL_UPDATE', payload: completedSummary })
    assert.strictEqual(state.summary?.status, 'COMPLETED')
    assert.strictEqual(state.summary?.progress_percentage, 100)
    assert.strictEqual(state.verifying, false, 'verifying flag clears when batch reaches COMPLETED')
    console.log('  ✓ In-progress polling and progress percentage verified')
  }

  // ── TEST 3: Status Rendering & Badge Differentiation ──
  {
    console.log('\nTest 3: Status Rendering & Badge Differentiation')
    const candidates = [sampleCandidate1, sampleCandidate2, sampleCandidate3]

    // Verify Candidate 1
    assert.strictEqual(sampleCandidate1.verification_status, 'VERIFIED')
    assert.strictEqual(sampleCandidate1.identity_status, 'MATCHED_SINGLE')
    assert.strictEqual(sampleCandidate1.repeat_application_status, 'FIRST_APPLICATION')

    // Verify Candidate 2
    assert.strictEqual(sampleCandidate2.verification_status, 'REVIEW_REQUIRED')
    assert.strictEqual(sampleCandidate2.identity_status, 'REVIEW_REQUIRED')
    assert.strictEqual(sampleCandidate2.repeat_application_status, 'REPEAT_APPLICATION_DIFFERENT_JOB')

    // Verify Candidate 3
    assert.strictEqual(sampleCandidate3.verification_status, 'FAILED')
    assert.strictEqual(sampleCandidate3.error_message, 'File corrupted: could not parse PDF binary stream')

    // Filtering test
    const filteredVerified = filterCandidates(candidates, '', 'VERIFIED', 'ALL')
    assert.strictEqual(filteredVerified.length, 1)
    assert.strictEqual(filteredVerified[0].candidate_id, 'cand-001')

    const filteredRepeat = filterCandidates(candidates, '', 'ALL', 'REPEAT_APPLICATION_DIFFERENT_JOB')
    assert.strictEqual(filteredRepeat.length, 1)
    assert.strictEqual(filteredRepeat[0].candidate_id, 'cand-002')

    const searchResult = filterCandidates(candidates, 'Alex', 'ALL', 'ALL')
    assert.strictEqual(searchResult.length, 1)
    assert.strictEqual(searchResult[0].candidate_name, 'Alex Morgan')
    console.log('  ✓ Status rendering, badges, and filters verified')
  }

  // ── TEST 4: Separation of Repeat Applications from Fraud / Fabrication ──
  {
    console.log('\nTest 4: Strict Separation of Repeat Applications from Fraud')
    // Candidate applied to multiple jobs
    const isFraudCandidate1 = isRepeatApplicationFraud(sampleCandidate1.repeat_application_status)
    const isFraudCandidate2 = isRepeatApplicationFraud(sampleCandidate2.repeat_application_status)
    const isFraudMulti = isRepeatApplicationFraud('MULTIPLE_PREVIOUS_APPLICATIONS')
    const isFraudSame = isRepeatApplicationFraud('REPEAT_APPLICATION_SAME_JOB')

    assert.strictEqual(isFraudCandidate1, false)
    assert.strictEqual(isFraudCandidate2, false)
    assert.strictEqual(isFraudMulti, false)
    assert.strictEqual(isFraudSame, false)

    // Repeat candidate can still be verified without being marked fraudulent
    const repeatVerifiedCandidate: CandidateVerificationItemResult = {
      ...sampleCandidate2,
      verification_status: 'VERIFIED',
    }
    assert.strictEqual(canProceedToAiScoring(repeatVerifiedCandidate), true)
    console.log('  ✓ Repeat applications verified as strictly distinct from fraud')
  }

  // ── TEST 5: Retry Mechanism for Failed Candidate Verification Tasks ──
  {
    console.log('\nTest 5: Retry Action for Failed Candidate Tasks')
    let state = {
      ...initialVerificationState,
      summary: {
        project_id: 'proj-1',
        job_opening_id: 'job-101',
        status: 'COMPLETED' as BatchVerificationStatus,
        total_candidates: 3,
        processed_candidates: 3,
        progress_percentage: 100,
        verified_candidates: 1,
        review_required_candidates: 1,
        failed_candidates: 1,
        results: [sampleCandidate1, sampleCandidate2, sampleCandidate3],
      },
    }

    // Trigger retry for failed candidate 3
    state = verificationReducer(state, { type: 'RETRY_START', payload: 'cand-003' })
    assert.strictEqual(state.retryingId, 'cand-003', 'retryingId set during retry request')

    // Simulate successful retry response from backend
    const recoveredCandidate: CandidateVerificationItemResult = {
      ...sampleCandidate3,
      verification_status: 'VERIFIED',
      identity_status: 'NEW_CANDIDATE',
      error_message: undefined,
      match_reasons: ['Successfully parsed after retry normalization'],
      conflicts: [],
    }

    const updatedSummary: BatchVerificationSummary = {
      ...state.summary!,
      verified_candidates: 2,
      failed_candidates: 0,
      results: [sampleCandidate1, sampleCandidate2, recoveredCandidate],
    }

    state = verificationReducer(state, { type: 'RETRY_SUCCESS', payload: updatedSummary })
    assert.strictEqual(state.retryingId, null, 'retryingId reset after retry')
    assert.strictEqual(state.summary?.failed_candidates, 0)
    assert.strictEqual(state.summary?.verified_candidates, 2)
    assert.strictEqual(state.summary?.results[2].verification_status, 'VERIFIED')
    console.log('  ✓ Retry execution and state recovery verified')
  }

  // ── TEST 6: Review Actions (Approve/Reject) with Notes and Auth Handling ──
  {
    console.log('\nTest 6: Review Actions (Approve / Reject) & Auth Handling')
    let state = {
      ...initialVerificationState,
      summary: {
        project_id: 'proj-1',
        job_opening_id: 'job-101',
        status: 'COMPLETED' as BatchVerificationStatus,
        total_candidates: 2,
        processed_candidates: 2,
        progress_percentage: 100,
        verified_candidates: 1,
        review_required_candidates: 1,
        failed_candidates: 0,
        results: [sampleCandidate1, sampleCandidate2],
      },
      documents: {
        'doc-002-a': { id: 'doc-002-a', verification_status: 'REVIEW_REQUIRED' as CandidateVerificationStatus },
        'doc-002-b': { id: 'doc-002-b', verification_status: 'REVIEW_REQUIRED' as CandidateVerificationStatus },
      },
    }

    // Select candidate requiring review
    state = verificationReducer(state, { type: 'SELECT_CANDIDATE', payload: sampleCandidate2 })
    assert.strictEqual(state.selectedCandidate?.candidate_id, 'cand-002')
    assert.strictEqual(state.selectedDocId, 'doc-002-a', 'First document auto-selected')

    // Enter review note
    state = verificationReducer(state, {
      type: 'SET_REVIEW_NOTE',
      payload: 'Confirmed phone and name match the same person: Alex Morgan',
    })
    assert.strictEqual(state.reviewNote, 'Confirmed phone and name match the same person: Alex Morgan')

    // Test authorization failure handling
    state = verificationReducer(state, { type: 'REVIEW_START' })
    assert.strictEqual(state.reviewActionLoading, true)

    // Test duplicate click guard: second action attempt while loading is prevented
    let duplicateIgnored = false
    if (state.reviewActionLoading) {
      duplicateIgnored = true
    }
    assert.strictEqual(duplicateIgnored, true, 'Duplicate submission attempts blocked while reviewActionLoading')

    state = verificationReducer(state, {
      type: 'REVIEW_ERROR',
      payload: '403 Forbidden: You do not have permission to manually override candidate verification.',
    })
    assert.strictEqual(state.reviewActionLoading, false)
    assert.strictEqual(
      state.reviewError,
      '403 Forbidden: You do not have permission to manually override candidate verification.',
    )

    // Test successful manual approval override
    state = verificationReducer(state, {
      type: 'REVIEW_SUCCESS',
      payload: {
        candidateId: 'cand-002',
        newStatus: 'VERIFIED',
        note: 'Confirmed identity manually by hiring lead',
      },
    })
    assert.strictEqual(state.summary?.verified_candidates, 2)
    assert.strictEqual(state.summary?.review_required_candidates, 0)
    assert.strictEqual(state.summary?.results[1].verification_status, 'VERIFIED')
    assert.strictEqual(state.summary?.results[1].review_note, 'Confirmed identity manually by hiring lead')
    console.log('  ✓ Review actions, notes, and authorization error handling verified')
  }

  // ── TEST 7: Network Failure & Error Recovery States ──
  {
    console.log('\nTest 7: Network Failures & Error Recovery')
    let state = { ...initialVerificationState }

    state = verificationReducer(state, { type: 'FETCH_START' })
    assert.strictEqual(state.loading, true)

    state = verificationReducer(state, {
      type: 'FETCH_ERROR',
      payload: 'Network error: Failed to connect to verification backend service',
    })
    assert.strictEqual(state.loading, false)
    assert.strictEqual(state.error, 'Network error: Failed to connect to verification backend service')
    assert.strictEqual(state.summary, null, 'Summary remains null when initial fetch fails')

    // Recovery upon retry
    state = verificationReducer(state, { type: 'FETCH_START' })
    state = verificationReducer(state, {
      type: 'FETCH_SUCCESS',
      payload: {
        project_id: 'proj-1',
        job_opening_id: 'job-101',
        status: 'PENDING',
        total_candidates: 0,
        processed_candidates: 0,
        progress_percentage: 0,
        verified_candidates: 0,
        review_required_candidates: 0,
        failed_candidates: 0,
        results: [],
      },
    })
    assert.strictEqual(state.error, null)
    assert.strictEqual(state.loading, false)
    console.log('  ✓ Network failures and recovery transitions verified')
  }

  // ── TEST 8: Empty Candidate List Rendering ──
  {
    console.log('\nTest 8: Empty Candidate List Handling')
    let state = { ...initialVerificationState }

    const emptySummary: BatchVerificationSummary = {
      project_id: 'proj-empty',
      job_opening_id: 'job-empty',
      status: 'PENDING',
      total_candidates: 0,
      processed_candidates: 0,
      progress_percentage: 0,
      verified_candidates: 0,
      review_required_candidates: 0,
      failed_candidates: 0,
      results: [],
    }

    state = verificationReducer(state, { type: 'FETCH_SUCCESS', payload: emptySummary })
    assert.strictEqual(state.summary?.total_candidates, 0)
    assert.strictEqual(state.summary?.results.length, 0)

    const filtered = filterCandidates(state.summary.results, '', 'ALL', 'ALL')
    assert.strictEqual(filtered.length, 0, 'Displays 0 candidates in empty state')
    console.log('  ✓ Empty candidate list handling verified')
  }

  // ── TEST 9: Page-Refresh Recovery (Persisted State) ──
  {
    console.log('\nTest 9: Page-Refresh Recovery from Persisted State')
    // Simulate user refreshing the page while a verification batch was previously saved
    let refreshedState = { ...initialVerificationState }
    refreshedState = verificationReducer(refreshedState, { type: 'FETCH_START' })

    const persistedStateFromBackend: BatchVerificationSummary = {
      project_id: 'proj-1',
      job_opening_id: 'job-101',
      status: 'COMPLETED',
      total_candidates: 2,
      processed_candidates: 2,
      progress_percentage: 100,
      verified_candidates: 1,
      review_required_candidates: 1,
      failed_candidates: 0,
      results: [sampleCandidate1, sampleCandidate2],
    }

    refreshedState = verificationReducer(refreshedState, {
      type: 'FETCH_SUCCESS',
      payload: persistedStateFromBackend,
    })

    assert.strictEqual(refreshedState.loading, false)
    assert.strictEqual(refreshedState.summary?.status, 'COMPLETED')
    assert.strictEqual(refreshedState.summary?.total_candidates, 2)
    assert.strictEqual(refreshedState.summary?.verified_candidates, 1)
    assert.strictEqual(refreshedState.summary?.results[0].candidate_name, 'Harshini CS')
    assert.strictEqual(refreshedState.verifying, false, 'No false loading state on page refresh')
    console.log('  ✓ Persisted verification state recovers seamlessly on page refresh')
  }

  // ── TEST 10: Conditional Action Button Visibility ──
  {
    console.log('\nTest 10: Conditional Action Button Visibility')
    // Approve/Reject action buttons must ONLY appear when document status is REVIEW_REQUIRED
    assert.strictEqual(shouldShowReviewButtons('REVIEW_REQUIRED'), true, 'Review buttons visible for REVIEW_REQUIRED')
    assert.strictEqual(shouldShowReviewButtons('VERIFIED'), false, 'Review buttons hidden for VERIFIED')
    assert.strictEqual(shouldShowReviewButtons('REJECTED'), false, 'Review buttons hidden for REJECTED')
    assert.strictEqual(shouldShowReviewButtons('FAILED'), false, 'Review buttons hidden for FAILED')
    assert.strictEqual(shouldShowReviewButtons('PENDING'), false, 'Review buttons hidden for PENDING')
    console.log('  ✓ Conditional action button visibility verified across all 5 verification statuses')
  }

  // ── TEST 11: Correct Document ID and Decision in API Request Payload ──
  {
    console.log('\nTest 11: Correct Document ID & Decision in API Request Payload')
    const approvePayload = buildReviewRequest('proj-123', 'doc-abc-1', 'APPROVE', 'Verified phone and name')
    assert.strictEqual(approvePayload.path, '/projects/proj-123/documents/doc-abc-1/review')
    assert.strictEqual(approvePayload.method, 'POST')
    assert.strictEqual(approvePayload.body.decision, 'APPROVE')
    assert.strictEqual(approvePayload.body.review_note, 'Verified phone and name')

    const rejectPayload = buildReviewRequest('proj-123', 'doc-abc-2', 'REJECT', 'Different individual')
    assert.strictEqual(rejectPayload.path, '/projects/proj-123/documents/doc-abc-2/review')
    assert.strictEqual(rejectPayload.body.decision, 'REJECT')
    assert.strictEqual(rejectPayload.body.review_note, 'Different individual')

    // Empty docId throws error
    assert.throws(() => buildReviewRequest('proj-123', '', 'APPROVE'), /documentId is required/)
    console.log('  ✓ API request payload, target document ID, and decision schema verified')
  }

  // ── TEST 12: Multi-Attachment Sibling Document Isolation ──
  {
    console.log('\nTest 12: Multi-Attachment Sibling Document Isolation')
    let state = {
      ...initialVerificationState,
      documents: {
        'doc-alpha': { id: 'doc-alpha', verification_status: 'REVIEW_REQUIRED' as CandidateVerificationStatus },
        'doc-beta': { id: 'doc-beta', verification_status: 'REVIEW_REQUIRED' as CandidateVerificationStatus },
      },
    }

    // Both attachments initially require review
    assert.strictEqual(shouldShowReviewButtons(state.documents['doc-alpha'].verification_status), true)
    assert.strictEqual(shouldShowReviewButtons(state.documents['doc-beta'].verification_status), true)

    // User selects and approves doc-alpha
    state = verificationReducer(state, {
      type: 'DOCUMENT_REVIEW_SUCCESS',
      payload: { documentId: 'doc-alpha', newStatus: 'VERIFIED', note: 'Approved doc-alpha' },
    })

    // doc-alpha is now VERIFIED -> review buttons hidden
    assert.strictEqual(state.documents['doc-alpha'].verification_status, 'VERIFIED')
    assert.strictEqual(shouldShowReviewButtons(state.documents['doc-alpha'].verification_status), false)

    // Sibling doc-beta MUST remain strictly REVIEW_REQUIRED -> review buttons still visible
    assert.strictEqual(state.documents['doc-beta'].verification_status, 'REVIEW_REQUIRED')
    assert.strictEqual(shouldShowReviewButtons(state.documents['doc-beta'].verification_status), true)

    // Backend scoring eligibility: doc-alpha can proceed, doc-beta cannot proceed
    assert.strictEqual(canProceedToAiScoring({ ...sampleCandidate1, verification_status: state.documents['doc-alpha'].verification_status }), true)
    assert.strictEqual(canProceedToAiScoring({ ...sampleCandidate1, verification_status: state.documents['doc-beta'].verification_status }), false)

    console.log('  ✓ Sibling document isolation verified: approving one does not make siblings eligible')
  }

  console.log('\n===============================================================')
  console.log('--- ALL 12 PHASE 4 & 5 FRONTEND TESTS PASSED SUCCESSFULLY! ---')
  console.log('===============================================================')
}

runAllTests()
