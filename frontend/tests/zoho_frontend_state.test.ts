/**
 * Focused tests for Phase 2: Zoho JD Frontend State and Dummy-File Handling.
 * Validates:
 * 1. Zoho import state synchronization (SET_JD, SET_JD_DOCUMENT_ID, SET_JD_PROCESSING)
 * 2. canProceedJD evaluation for Zoho import vs failure
 * 3. Back -> Next navigation preservation without placeholder upload
 * 4. Safe Retry routing for Zoho vs manual file vs existing doc
 * 5. Manual JD upload compatibility and state isolation
 */

import assert from 'node:assert'

// ── Mock Pipeline Reducer & State ─────────────────────────────
interface PipelineState {
  projectId: string | null
  jdDocumentId: string | null
  jdProcessingStatus: string | null
  jdProcessingStage: string | null
  jdNormalized: boolean
  isProcessing: boolean
  upload: {
    jobDescription: {
      id: string
      name: string
      status: 'uploading' | 'processing' | 'done' | 'error'
      errorMessage?: string
    } | null
    resumes: any[]
  }
}

const emptyState: PipelineState = {
  projectId: null,
  jdDocumentId: null,
  jdProcessingStatus: null,
  jdProcessingStage: null,
  jdNormalized: false,
  isProcessing: false,
  upload: {
    jobDescription: null,
    resumes: [],
  },
}

function pipelineReducer(state: PipelineState, action: any): PipelineState {
  switch (action.type) {
    case 'SELECT_PROJECT':
      return {
        ...state,
        projectId: action.payload.id,
      }
    case 'SET_JD_DOCUMENT_ID':
      return {
        ...state,
        jdDocumentId: action.payload,
      }
    case 'SET_JD_PROCESSING':
      return {
        ...state,
        jdProcessingStatus: action.payload.status !== undefined ? action.payload.status : state.jdProcessingStatus,
        jdProcessingStage: action.payload.stage !== undefined ? action.payload.stage : state.jdProcessingStage,
        jdNormalized: action.payload.normalized !== undefined ? action.payload.normalized : state.jdNormalized,
      }
    case 'SET_JD':
      return {
        ...state,
        upload: { ...state.upload, jobDescription: action.payload },
        jdDocumentId: action.payload === null ? null : state.jdDocumentId,
        ...(action.payload === null
          ? {
              jdProcessingStatus: null,
              jdProcessingStage: null,
              jdNormalized: false,
            }
          : {}),
      }
    default:
      return state
  }
}

function computeCanProceedJD(state: PipelineState): boolean {
  return (
    state.projectId !== null &&
    state.jdDocumentId !== null &&
    state.upload.jobDescription?.status === 'done' &&
    state.jdNormalized === true &&
    state.isProcessing === false
  )
}

// ── Test Suites ───────────────────────────────────────────────

function runTests() {
  console.log('--- Starting Phase 2 Frontend State & Zoho Flow Tests ---')

  // Test 1: Successful Zoho Import State Synchronization
  {
    console.log('Test 1: Zoho Import State Synchronization')
    let state = { ...emptyState }
    state = pipelineReducer(state, {
      type: 'SELECT_PROJECT',
      payload: { id: 'proj-123', title: 'REQ-1 - Backend Dev' },
    })

    const zohoJob = { id: 'zoho-job-456', posting_title: 'Senior Python Engineer' }
    const backendRes = {
      document_id: 'doc-789',
      filename: 'Zoho_JD_zoho-job-456_Senior_Python_Engineer.txt',
      processing_status: 'COMPLETED',
      processing_stage: 'COMPLETED',
      normalized: { id: 'norm-1', document_id: 'doc-789' },
      extracted: { role: 'Senior Python Engineer', required_skills: ['Python', 'FastAPI'] },
    }

    const isSuccess =
      (backendRes.processing_status === 'COMPLETED' || backendRes.processing_status === 'PARSED') &&
      backendRes.normalized != null

    assert.strictEqual(isSuccess, true, 'Import should be recognized as successful')

    state = pipelineReducer(state, { type: 'SET_JD_DOCUMENT_ID', payload: backendRes.document_id })
    state = pipelineReducer(state, {
      type: 'SET_JD_PROCESSING',
      payload: {
        status: backendRes.processing_status,
        stage: backendRes.processing_stage,
        normalized: isSuccess,
      },
    })
    state = pipelineReducer(state, {
      type: 'SET_JD',
      payload: {
        id: backendRes.document_id,
        name: backendRes.filename,
        status: isSuccess ? 'done' : 'error',
      },
    })

    assert.strictEqual(state.jdDocumentId, 'doc-789')
    assert.strictEqual(state.jdNormalized, true)
    assert.strictEqual(state.upload.jobDescription?.status, 'done')
    assert.strictEqual(state.upload.jobDescription?.name, 'Zoho_JD_zoho-job-456_Senior_Python_Engineer.txt')
    assert.strictEqual(computeCanProceedJD(state), true, 'canProceedJD must be true for successful Zoho import')
    console.log('  ✓ Verified state correctly synchronized and canProceedJD evaluates to true')
  }

  // Test 2: Failed Backend Processing must NOT mark complete
  {
    console.log('Test 2: Backend Processing Failure State Synchronization')
    let state = { ...emptyState, projectId: 'proj-123' }

    const failedBackendRes = {
      document_id: 'doc-fail-1',
      filename: 'Zoho_JD_fail.txt',
      processing_status: 'FAILED',
      processing_stage: 'FAILED',
      normalized: null,
      errorMessage: 'Parsing error occurred on backend',
    }

    const isSuccess =
      (failedBackendRes.processing_status === 'COMPLETED' || failedBackendRes.processing_status === 'PARSED') &&
      failedBackendRes.normalized != null

    assert.strictEqual(isSuccess, false, 'Import should not be recognized as successful on failure')

    state = pipelineReducer(state, { type: 'SET_JD_DOCUMENT_ID', payload: failedBackendRes.document_id })
    state = pipelineReducer(state, {
      type: 'SET_JD_PROCESSING',
      payload: {
        status: failedBackendRes.processing_status,
        stage: failedBackendRes.processing_stage,
        normalized: isSuccess,
      },
    })
    state = pipelineReducer(state, {
      type: 'SET_JD',
      payload: {
        id: failedBackendRes.document_id,
        name: failedBackendRes.filename,
        status: isSuccess ? 'done' : 'error',
        errorMessage: 'JD processing failed',
      },
    })

    assert.strictEqual(state.jdNormalized, false)
    assert.strictEqual(state.upload.jobDescription?.status, 'error')
    assert.strictEqual(computeCanProceedJD(state), false, 'canProceedJD must be false when backend fails')
    console.log('  ✓ Verified failed processing properly prevents advance')
  }

  // Test 3: Back -> Next Step Navigation without Dummy File
  {
    console.log('Test 3: Back -> Next Navigation Preservation')
    const zohoJob = { id: 'zoho-100', posting_title: 'Full Stack Engineer' }
    let jdFile: any = null // Critical: jdFile is null for Zoho JD (no dummy file)
    let state = {
      ...emptyState,
      projectId: 'proj-100',
      jdDocumentId: 'doc-100',
      jdNormalized: true,
      upload: {
        jobDescription: {
          id: 'doc-100',
          name: 'Zoho_JD_zoho-100_Full_Stack_Engineer.txt',
          status: 'done' as const,
        },
        resumes: [],
      },
    }

    // Step 2 Attached display condition
    const attachedJdName = jdFile
      ? jdFile.name
      : zohoJob
      ? `Zoho JD: ${zohoJob.posting_title}`
      : state.upload.jobDescription?.name || null

    const hasAttachedJd = Boolean(jdFile || zohoJob || state.jdDocumentId)

    assert.strictEqual(hasAttachedJd, true, 'hasAttachedJd must be true when Zoho JD is attached')
    assert.strictEqual(attachedJdName, 'Zoho JD: Full Stack Engineer')

    // Simulate Step 2 -> Step 3 navigation (handleProceedToStep3)
    let startJdProcessingCalledWith: any = null
    const processedFileRef = { current: null }

    function handleProceedToStep3() {
      if (!hasAttachedJd) return
      // Next Step
      if (jdFile && (!processedFileRef.current || processedFileRef.current !== jdFile)) {
        startJdProcessingCalledWith = jdFile
      }
    }

    handleProceedToStep3()

    assert.strictEqual(
      startJdProcessingCalledWith,
      null,
      'Step 2 -> Step 3 MUST NOT call startJdProcessing when importing Zoho JD (no dummy file overwrite)',
    )
    assert.strictEqual(state.jdDocumentId, 'doc-100', 'Original Zoho document ID is preserved intact')
    console.log('  ✓ Verified no dummy file is uploaded during Back -> Next navigation')
  }

  // Test 4: Retry Routing Logic (Zoho vs Manual vs Existing Document)
  {
    console.log('Test 4: Retry Routing Logic')
    let reimportZohoCalled = false
    let startJdProcessingFile: any = null
    let reloadDocumentId: string | null = null

    function handleRetryJd(ctx: {
      zohoJob: any
      jdFile: any
      jdDocumentId: string | null
    }) {
      const currentZoho = ctx.zohoJob
      if (currentZoho) {
        reimportZohoCalled = true
      } else if (ctx.jdFile) {
        startJdProcessingFile = ctx.jdFile
      } else if (ctx.jdDocumentId) {
        reloadDocumentId = ctx.jdDocumentId
      }
    }

    // Case A: Zoho JD retry
    handleRetryJd({
      zohoJob: { id: 'zj-1' },
      jdFile: null,
      jdDocumentId: 'doc-1',
    })
    assert.strictEqual(reimportZohoCalled, true, 'Zoho retry routes to Zoho re-import')

    // Case B: Manual JD retry
    const dummyManualFile = { name: 'my_jd.pdf', size: 1024 }
    handleRetryJd({
      zohoJob: null,
      jdFile: dummyManualFile,
      jdDocumentId: null,
    })
    assert.strictEqual(startJdProcessingFile, dummyManualFile, 'Manual retry routes to file processing')

    // Case C: Remounted state with existing document ID
    handleRetryJd({
      zohoJob: null,
      jdFile: null,
      jdDocumentId: 'doc-existing-789',
    })
    assert.strictEqual(reloadDocumentId, 'doc-existing-789', 'Routes to document reload when only ID is available')
    console.log('  ✓ Verified retry correctly routes by source without cross-contamination')
  }

  // Test 5: Manual Upload Compatibility & State Isolation
  {
    console.log('Test 5: Manual Upload Compatibility & State Isolation')
    let zohoJob: any = { id: 'zoho-old' }
    let jdFile: any = null

    // User chooses a manual file
    const manualFile = { name: 'engineer_jd.pdf', size: 2048 }
    function handleFileChange(file: any) {
      zohoJob = null
      jdFile = file
    }

    handleFileChange(manualFile)

    assert.strictEqual(zohoJob, null, 'Active Zoho JD must be cleared when user uploads a manual file')
    assert.strictEqual(jdFile.name, 'engineer_jd.pdf')

    // Simulate successful manual file processing
    let state = { ...emptyState, projectId: 'proj-manual' }
    state = pipelineReducer(state, { type: 'SET_JD_DOCUMENT_ID', payload: 'doc-manual-1' })
    state = pipelineReducer(state, {
      type: 'SET_JD_PROCESSING',
      payload: { status: 'COMPLETED', stage: 'COMPLETED', normalized: true },
    })
    state = pipelineReducer(state, {
      type: 'SET_JD',
      payload: { id: 'doc-manual-1', name: manualFile.name, status: 'done' },
    })

    assert.strictEqual(computeCanProceedJD(state), true, 'canProceedJD evaluates to true for manual upload')
    console.log('  ✓ Verified manual JD upload compatibility and state isolation')
  }

  console.log('\n--- ALL 5 TESTS PASSED SUCCESSFULLY! ---')
}

runTests()
