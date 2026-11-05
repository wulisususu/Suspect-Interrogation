import { http } from './http'

export type DocumentExportFormat = 'DOCX' | 'PDF'

export interface DocumentExportRecord {
  id: string
  caseId: string
  format: DocumentExportFormat
  fileName: string
  snapshotId: string
  sha256: string
  sizeBytes: number
  createdAt: string
  signatureCount: number
  downloadUrl: string
}

function unwrap<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'ok' in payload) {
    const envelope = payload as { ok: boolean; data?: T; code?: string; message?: string }
    if (!envelope.ok) throw new Error(envelope.message || envelope.code || '导出接口返回错误')
    return ('data' in envelope ? envelope.data : payload) as T
  }
  return payload as T
}

/** 在后端按冻结快照生成导出件（DOCX 只需冻结；PDF 还要求双方签署与指纹捺印）。 */
export async function createDocumentExport(
  caseId: string,
  format: DocumentExportFormat,
): Promise<DocumentExportRecord> {
  const response = await http.post(`/api/v1/cases/${caseId}/exports`, { format })
  return unwrap<DocumentExportRecord>(response.data)
}

export async function listDocumentExports(caseId: string): Promise<DocumentExportRecord[]> {
  const response = await http.get(`/api/v1/cases/${caseId}/exports`)
  return unwrap<DocumentExportRecord[]>(response.data)
}

export async function downloadDocumentExport(caseId: string, exportId: string): Promise<Blob> {
  const response = await http.get(`/api/v1/cases/${caseId}/exports/${exportId}/file`, {
    responseType: 'blob',
    timeout: 120_000,
  })
  return response.data as Blob
}

/** 生成并直接触发浏览器下载，返回落盘用的文件名。 */
export async function exportDocumentToFile(
  caseId: string,
  format: DocumentExportFormat,
): Promise<string> {
  const record = await createDocumentExport(caseId, format)
  const blob = await downloadDocumentExport(caseId, record.id)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = record.fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
  return record.fileName
}
