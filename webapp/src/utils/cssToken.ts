/** Canvas 绘图拿不到 CSS 变量，这里从根元素读出 tokens.css 的实际值。 */
export function cssToken(name: string, fallback: string): string {
  if (typeof document === 'undefined' || typeof getComputedStyle === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}
