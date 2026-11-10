import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const source = readFileSync(fileURLToPath(new URL('./InterrogationWorkspace.vue', import.meta.url)), 'utf-8')

describe('workspace landing step', () => {
  it('opens a brand-new case straight on ① 选模板 instead of flashing ② 建档 first', () => {
    // 从大厅新建的案件带 startAtTemplate；初始化时必须直接落在 template，
    // 否则会先渲染 intake、等案件与模板加载完再跳回，肉眼就是"进去又跳回来"。
    expect(source).toContain("const landingStep = props.startAtTemplate ? 'template' : 'intake'")
    expect(source).toContain('flowStep.value = landingStep')
    expect(source).toContain('activePage.value = pageForStep(landingStep)')
    // 不再无条件先设成建档页
    expect(source).not.toContain("activePage.value = 'profile'\n    flowStep.value = 'intake'")
  })
})
