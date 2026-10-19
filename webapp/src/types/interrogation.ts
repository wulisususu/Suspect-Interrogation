export type Speaker = '民警' | '嫌疑人' | 'AI'
export type RecordMark = '' | 'conflict' | 'confirmed' | 'pending'
export type SessionStatus = 'READY' | 'RUNNING' | 'PAUSED' | 'COMPLETED'
export type InterrogationStage = 'IDENTITY' | 'STATEMENT' | 'FOLLOW_UP' | 'SIGNING'
export type AiProviderKind = 'LOCAL' | 'UNAVAILABLE'
export type ModelCategory = 'ASR' | 'OCR' | 'VAD' | 'SPEAKER' | 'LLM'
export type ModelSourceKind = 'FILE' | 'DIRECTORY' | 'ASSET'
export type ModelImportSource = 'FILE' | 'DIRECTORY'
export type DocumentSignerRole = 'SUSPECT' | 'OFFICER'
export type DocumentSigningStatus = 'FROZEN' | 'LOCKED'

export interface TranscriptMessage {
  id: string
  seq?: number
  speaker: Speaker
  text: string
  mark?: RecordMark
  createdAt?: number | string
  updatedAt?: number | string
  streaming?: boolean
  confirmed?: boolean
}

export type FactStatus = 'confirmed' | 'pending' | 'conflict' | 'missing'

export interface FactItem {
  key: string
  label: string
  value: string
  status: FactStatus
  suggestion?: string
}

export interface CaseSummary {
  id: string
  suspectName: string
  gender?: string
  age?: string
  idNumber?: string
  nation?: string
  birthDate?: string
  address?: string
  identitySource?: 'MANUAL' | 'OCR' | string
  identityCapturedAt?: number | null
  officerName: string
  state: string
  workflowState?: string
  documentStatus?: string
  reportStatus?: string
  caseType?: string
  stage: InterrogationStage
  createdAt?: number
  updatedAt?: number
}

export interface SessionState {
  id: string | null
  caseId: string
  status: SessionStatus
  stage: InterrogationStage
  startedAt: number | null
  pausedAt: number | null
  endedAt: number | null
  updatedAt: number
}

export interface RecordRevision {
  id: string
  qaId: string
  version: number
  oldText: string
  newText: string
  reason: string
  createdAt: number
}

export interface DeviceActionResult {
  success: boolean
  simulated?: boolean
  message?: string
  name?: string
  gender?: string
  idNumber?: string
}

export interface InquirySsePayload {
  text_chunk?: string
  audio_url?: string
  target?: number
  infos?: Record<string, unknown>
  code?: number
  message?: string
}

export interface LocalModelDescriptor {
  id: string
  category: ModelCategory
  name: string
  storageName: string
  relativePath: string
  sizeBytes: number
  modifiedAt: number
  sourceKind: ModelSourceKind
  archive: boolean
  selected: boolean
  runtimeReady: boolean
  version?: string | null
  modelFormat?: string | null
  provider?: string | null
  complete?: boolean
  targetPlatform?: 'RK3576' | 'RK3588' | 'UNKNOWN' | string | null
  compatibility?: 'READY' | 'INCOMPLETE' | 'UNREADABLE' | 'PLATFORM_MISMATCH' | 'UNSUPPORTED' | string | null
}

export interface CaseAiAnalysis {
  id: string
  caseId: string
  text: string
  provider: AiProviderKind
  model: string
  createdAt: number
}

export interface LocalModelCatalog {
  rootPath: string
  models: LocalModelDescriptor[]
}

export interface AsrFinalResult {
  text: string
  startedAtMs: number
  endedAtMs: number
  latencyMs: number
  confidence?: number | null
}

export interface AsrRuntimeStatus {
  selectedModelId: string
  selectedModelName: string
  activeModelId?: string | null
  provider: 'rknn' | 'cpu'
  running: boolean
  initialized: boolean
  initializationMs?: number | null
  firstTokenLatencyMs?: number | null
  utteranceLatencyMs?: number | null
  partialText: string
  finalText: string
  finalResults: AsrFinalResult[]
  error?: string | null
  sherpaVersion: string
  sampleRate: number
  preferredAudioInput?: string | null
  routedAudioInput?: string | null
  audioPeak?: number | null
  audioSignalState?: 'WAITING' | 'ACTIVE' | 'SILENT'
}

export type TemporaryAsrSpeaker =
  | 'UNKNOWN'
  | 'OFFICER_FALLBACK'
  | 'INTERROGATOR'
  | 'RECORDER'
  | 'SUSPECT'

export type AsrSpeakerSource =
  | 'UNASSIGNED'
  | 'PENDING_ANALYSIS'
  | 'X_VECTOR'
  | 'SPEAKER_EMBEDDING'
  | 'SUSPECT_EXCLUSION'
  | 'MANUAL'

export type TemporaryAsrFragmentState = 'PENDING' | 'EDITED' | 'CONFIRMED' | 'DISCARDED' | 'SUPERSEDED'
export type AsrConfidenceSource = 'SHERPA_TOKEN_LOG_PROBS' | 'FUNASR' | 'UNAVAILABLE'

export interface AsrFragmentLineage {
  analysisJobId: string
  parentFragmentId: string
  childFragmentId: string
  relation: string
}

export interface AsrAudioReference {
  captureSessionId: string
  startOffsetMs: number
  endOffsetMs: number
  available: boolean
}

export interface AsrRecognitionEvidence {
  evidenceId: string
  aiSpeaker: TemporaryAsrSpeaker
  speakerId?: string | null
  speakerName?: string | null
  speakerSource: AsrSpeakerSource
  score?: number | null
  secondBestScore?: number | null
  threshold?: number | null
  margin?: number | null
  thresholdSource?: string | null
  voiceprintVerified: boolean
  lowConfidence: boolean
  asrModelId?: string | null
  asrModelVersion?: string | null
  speakerModelId?: string | null
  speakerModelVersion?: string | null
  speakerModelFingerprint?: string | null
  microphoneFingerprint?: string | null
  calibrationId?: string | null
  calibrationStatus?: string | null
  createdAt?: number | null
}

export interface AsrRecognitionRevision {
  revisionId: string
  revisionNo: number
  beforeSpeaker: TemporaryAsrSpeaker
  afterSpeaker: TemporaryAsrSpeaker
  beforeText: string
  afterText: string
  actorId?: string | null
  reason?: string | null
  createdAt?: number | null
}

export interface TemporaryAsrFragment {
  id: string
  captureSessionId: string
  caseId: string
  ordinal: number
  captureStartedAt?: number | null
  startedAtMs: number
  endedAtMs: number
  rawText: string
  editedText: string
  speaker: TemporaryAsrSpeaker
  speakerId?: string | null
  speakerName?: string | null
  speakerScore?: number | null
  secondBestScore?: number | null
  speakerThreshold?: number | null
  speakerMargin?: number | null
  speakerSource: AsrSpeakerSource
  voiceprintVerified: boolean
  confidence?: number | null
  confidenceSource: AsrConfidenceSource
  lowConfidence: boolean
  state: TemporaryAsrFragmentState
  confirmedQaId?: string | null
  confirmedMessageId?: string | null
  modelId?: string | null
  modelVersion?: string | null
  recognitionEvidence?: AsrRecognitionEvidence | null
  recognitionRevisions: AsrRecognitionRevision[]
  lineage?: AsrFragmentLineage[]
  /**
   * Task 17B-1: the mode the fragment was decided in, as published on ASR_FRAGMENT.
   * A narrowed operating point (no calibrated margin) reports SUSPECT_ONLY with
   * `recognitionModeDegraded === true` even when the session declared more.
   */
  declaredRecognitionMode?: VoiceRecognitionMode
  effectiveRecognitionMode?: VoiceRecognitionMode
  recognitionModeDegraded?: boolean
  recognitionModeDegradedReason?: string | null
  audio: AsrAudioReference
  createdAt: number
  updatedAt: number
}

export interface AudioLevelSample {
  sampleCount: number
  sampleRate: number
  rms: number
  peak: number
}

export interface AsrCaptureStatus {
  caseId: string
  captureSessionId?: string | null
  source?: 'BROWSER' | 'ALSA' | null
  running: boolean
  startedAt?: number | null
  endedAt?: number | null
  modelId?: string | null
  modelName?: string | null
  provider?: 'rknn' | 'cpu' | null
  recordingStatus?: 'PENDING' | 'CAPTURING' | 'COMPLETE' | 'INCOMPLETE' | string | null
  asrStatus?: 'PENDING' | 'FINALIZING' | 'COMPLETE' | 'ERROR' | string | null
  speakerStatus?: 'PENDING' | 'QUEUED' | 'RUNNING' | 'COMPLETE' | 'NEEDS_REVIEW' | 'ERROR' | string | null
  audioSampleCount?: number
  asrCursorSample?: number
  voicedMs?: number
  finalFragmentCount?: number
  audioLevels?: AudioLevelSample[]
  audioLevelUpdatedAt?: number | null
  sampleRate: number
  partialText: string
  partialStartedAtMs?: number | null
  partialEndedAtMs?: number | null
  liveTranscriptStatus?: 'AVAILABLE' | 'MODEL_NOT_INSTALLED' | 'ERROR' | 'UNKNOWN' | string | null
  fragments: TemporaryAsrFragment[]
  error?: string | null
}

export type VoiceRecognitionMode =
  | 'SUSPECT_ONLY'
  | 'SUSPECT_PLUS_INTERROGATOR'
  | 'SUSPECT_PLUS_RECORDER'
  | 'FULL'

export type SpeakerBackendKey = 'eres2net_large'

export interface VoiceprintBackendReadiness {
  suspectReady: boolean
  interrogatorReady: boolean
  recorderReady: boolean
  recognitionMode: VoiceRecognitionMode
  canStart: boolean
}

export interface VoiceprintReadiness extends VoiceprintBackendReadiness {
  selectedSpeakerBackend?: SpeakerBackendKey
  authoritativeSpeakerBackend?: SpeakerBackendKey
  simulated?: boolean
  /**
   * Registration metrics of the active suspect voiceprint used by the condensed re-record card.
   * Task 17B-1 populates them from the backend readiness payload; the card still degrades
   * gracefully when a deployment returns an older payload.
   */
  enrollmentQuality?: string | null
  usableDurationMs?: number | null
  modelKey?: SpeakerBackendKey | string | null
  modelId?: string | null
  modelVersion?: string | null
  /** Runtime speaker operating point behind the recognition mode decision. */
  speakerMargin?: number | null
  speakerThreshold?: number | null
  thresholdSource?: string | null
  marginConfigured?: boolean
  thresholdConfigured?: boolean
  /**
   * `recognitionMode` is what the bound roles declare. The runtime narrows to suspect-only
   * exactly when it has no calibrated margin, so `effectiveRecognitionMode` is the mode
   * that will really be enforced and `recognitionModeDegraded` says the two differ.
   *
   * Task 17B-1: read `recognitionModeVerified` first. When it is false the backend could
   * not check the operating point against the capture runtime's own resolver, so neither
   * mode field is reported (both are `undefined`, not `false`) and neither "mode
   * available" nor "not degraded" may be shown.
   */
  declaredRecognitionMode?: VoiceRecognitionMode
  effectiveRecognitionMode?: VoiceRecognitionMode
  recognitionModeDegraded?: boolean
  recognitionModeDegradedReason?: string | null
  /** true only when the mode was resolved from the runtime's own operating point. */
  recognitionModeVerified?: boolean
  /** LIVE_CAPTURE | DEVICE_CALIBRATION | UNVERIFIED. */
  recognitionModeVerificationSource?: string
}

export interface VoiceprintRoleDraft {
  caseId: string
  interrogatorOfficerId: string | null
  recorderOfficerId: string | null
}

export interface OfficerVoiceprint {
  voiceprintId?: string
  officerId: string
  officerName: string
  active: boolean
  modelId: string
  modelVersion?: string | null
  enrollmentQuality: string
  usableDurationMs: number
  revokedAt?: number | string | null
  simulated?: boolean
}

export type VoiceprintEnrollmentKind = 'SUSPECT' | 'OFFICER'
export type VoiceprintEnrollmentPhase = 'IDLE' | 'RECORDING' | 'PROCESSING' | 'COMPLETE' | 'ERROR'

export interface VoiceprintEnrollmentState {
  phase: VoiceprintEnrollmentPhase
  kind?: VoiceprintEnrollmentKind | null
  subjectId?: string | null
  officerName?: string | null
  usableDurationMs?: number | null
  capturedDurationMs?: number | null
  targetDurationMs?: number | null
  captureComplete?: boolean
  message?: string | null
  simulated?: boolean
}

export interface VoiceprintCaptureStatus {
  active: boolean
  kind?: string | null
  subjectId?: string | null
  capturedDurationMs: number
  targetDurationMs: number
  complete: boolean
}

export interface VoiceprintEnrollmentResult {
  ready?: boolean
  state?: string
  caseId?: string
  voiceprintId?: string
  officerId?: string
  officerName?: string
  active?: boolean
  usableDurationMs?: number
  modelId?: string
  modelVersion?: string | null
  quality?: string
  simulated?: boolean
  [key: string]: unknown
}

export interface AsrInsertionTarget {
  caseId: string
  recordId: string
  selectionStart: number
  selectionEnd: number
  sourceText: string
}

export interface AsrInsertionReceipt {
  caseId: string
  recordId: string
  caretPosition: number
  appliedAt: number
}

export interface FragmentApplication {
  fragments: TemporaryAsrFragment[]
  record: TranscriptMessage
}

export interface OcrPoint { x: number; y: number }
export interface OcrRect { left: number; top: number; right: number; bottom: number }
export interface OcrTextBlock { text: string; confidence?: number | null; rect?: OcrRect | null; points?: OcrPoint[] | null }
export interface OcrResult {
  text: string
  blocks: OcrTextBlock[]
  imageWidth: number
  imageHeight: number
  modelName: string
  provider: string
  initializationMs?: number | null
  recognitionMs: number
  previewUri?: string | null
}
export interface OcrRuntimeStatus {
  selectedModelId?: string | null
  selectedModelName?: string | null
  activeModelId?: string | null
  provider?: string | null
  modelFormat?: string | null
  initialized: boolean
  busy: boolean
  imageReady: boolean
  previewUri?: string | null
  initializationMs?: number | null
  recognitionMs?: number | null
  lastResult?: OcrResult | null
  error?: string | null
}

export interface LlmGenerationConfig {
  maxNewTokens: number
  maxContextLen: number
}

export interface LlmGenerateRequest extends LlmGenerationConfig {
  generationId: string
  prompt: string
}

export interface LlmFragment {
  generationId: string
  text: string
  accumulatedText: string
  tokenId?: number | null
  elapsedMs: number
}

export interface LlmResult {
  outputText: string
  finished: boolean
  fragments: string[]
  tokenIds?: number[] | null
  modelName: string
  provider: string
  maxNewTokens: number
  maxContextLen: number
  initializationMs: number
  firstTokenLatencyMs?: number | null
  totalInferenceMs: number
  error?: string | null
}

export interface LlmRuntimeStatus {
  selectedModelId?: string | null
  selectedModelName?: string | null
  activeModelId?: string | null
  provider: string
  storagePermissionGranted: boolean
  initialized: boolean
  busy: boolean
  generationId?: string | null
  config: LlmGenerationConfig
  initializationMs?: number | null
  firstTokenLatencyMs?: number | null
  totalInferenceMs?: number | null
  error?: string | null
}

export interface DocumentSignatureState {
  signerRole: DocumentSignerRole
  signerName: string
  signedAt: number
  signatureHash: string
  imageDataUrl: string
  strokesJson: string
  deviceId: string
}

export interface DocumentSigningState {
  caseId: string
  version: number
  documentId: string
  documentHash: string
  status: DocumentSigningStatus
  createdAt: number
  integrityValid: boolean
  signatures: DocumentSignatureState[]
}

export interface FragmentConfirmation { fragment: TemporaryAsrFragment; record: TranscriptMessage }
export interface BatchFragmentConfirmation {
  confirmed: FragmentConfirmation[]
  failures: Array<{ fragmentId: string; code: string; message: string }>
}

export interface BackendEnvelope<T> {
  ok: boolean
  code: string
  message: string
  data: T
}
