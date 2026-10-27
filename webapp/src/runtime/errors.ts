import type { RuntimeCapabilityName, RuntimeCapabilityState } from './types'

export class RuntimeAdapterError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly state: RuntimeCapabilityState = 'ERROR',
    public readonly capability?: RuntimeCapabilityName,
    public readonly cause?: unknown,
  ) {
    super(message)
    this.name = 'RuntimeAdapterError'
  }
}

export function operationCapability(operation: string): RuntimeCapabilityName | undefined {
  if (operation.startsWith('identity.')) return 'identity'
  if (operation.startsWith('ocr.')) return 'ocr'
  if (operation.startsWith('llm.') || operation.startsWith('ai.') || operation.startsWith('case.ai.')) return 'llm'
  if (operation.startsWith('asr.capture.')) return 'recording'
  if (operation.startsWith('asr.')) return 'asr'
  if (operation.startsWith('document.') || operation === 'device.signature') return 'signature'
  if (operation.startsWith('report.')) return 'report'
  if (operation === 'device.fingerprint') return 'fingerprint'
  if (operation.startsWith('device.')) return 'identity'
  return undefined
}

function responseStatus(error: unknown): number | undefined {
  const candidate = error as { response?: { status?: number } }
  return candidate?.response?.status
}

function responseData(error: unknown): Record<string, unknown> | undefined {
  const candidate = error as { response?: { data?: unknown } }
  return candidate?.response?.data && typeof candidate.response.data === 'object'
    ? candidate.response.data as Record<string, unknown>
    : undefined
}

export function normalizeRuntimeError(error: unknown, operation: string): RuntimeAdapterError {
  if (error instanceof RuntimeAdapterError) return error

  const capability = operationCapability(operation)
  const candidate = error as { code?: string; message?: string }
  const status = responseStatus(error)
  const data = responseData(error)
  const backendCode = typeof data?.code === 'string' ? data.code : undefined
  const backendMessage = typeof data?.message === 'string' ? data.message : undefined

  if (candidate?.code === 'ERR_NETWORK' || candidate?.code === 'ECONNABORTED' || candidate?.code === 'ETIMEDOUT') {
    return new RuntimeAdapterError('BACKEND_OFFLINE', '无法连接 Linux 本地后端', 'NOT_CONNECTED', capability, error)
  }

  if (backendCode === 'MODEL_NOT_INSTALLED') {
    return new RuntimeAdapterError(backendCode, backendMessage || '本地模型尚未安装', 'MODEL_NOT_INSTALLED', capability, error)
  }
  if (backendCode === 'NOT_CONFIGURED') {
    return new RuntimeAdapterError(backendCode, backendMessage || '本地能力尚未配置', 'NOT_CONFIGURED', capability, error)
  }
  if (backendCode === 'BUSY') {
    return new RuntimeAdapterError(backendCode, backendMessage || '本地能力正在忙碌', 'BUSY', capability, error)
  }

  // 404/501 只有在"路由本身不存在"时才说明能力没装：后端对未知路由统一返回
  // code=NOT_FOUND（app/api/errors.py），FastAPI 原生 404 则完全没有 code。
  // 带具体领域码的 404 是业务找不到资源（如 ASR_FRAGMENT_NOT_FOUND），
  // 改写成"模型未安装"会把现场排障引到模型目录而不是数据本身。
  const routeMissing = !backendCode || backendCode === 'NOT_FOUND'
  if ((status === 404 || status === 501) && routeMissing) {
    const modelFeature = capability === 'asr' || capability === 'ocr' || capability === 'llm' || capability === 'recording'
    return new RuntimeAdapterError(
      modelFeature ? 'MODEL_NOT_INSTALLED' : 'CAPABILITY_NOT_CONFIGURED',
      modelFeature ? '对应 Linux 本地模型/运行时尚未安装' : '对应 Linux 本地能力尚未配置',
      modelFeature ? 'MODEL_NOT_INSTALLED' : 'NOT_CONFIGURED',
      capability,
      error,
    )
  }

  return new RuntimeAdapterError(
    backendCode || candidate?.code || 'RUNTIME_ERROR',
    backendMessage || candidate?.message || String(error),
    'ERROR',
    capability,
    error,
  )
}
