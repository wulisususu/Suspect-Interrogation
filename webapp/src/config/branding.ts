/**
 * 品牌与部署单位信息。
 * 单位名、大厅名、卷号字头随部署环境变化，从 VITE_* 读取；未配置时留空，界面不显示示例单位。
 */
function env(name: string): string {
  const value = (import.meta.env as Record<string, string | undefined>)[name]
  return typeof value === 'string' ? value.trim() : ''
}

export const branding = {
  productName: '公安笔录智能工作台',
  unitName: env('VITE_UNIT_NAME'),
  venueName: env('VITE_VENUE_NAME'),
  volumePrefix: env('VITE_VOLUME_PREFIX') || null,
}
