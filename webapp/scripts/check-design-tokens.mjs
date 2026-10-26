// 设计令牌检查：样式里不允许裸色值（#hex / 不透明 rgb()），颜色一律走 tokens.css。
// 半透明 rgba() 用于阴影与遮罩，令牌无法表达透明度变体，允许保留。
// 字号同理只走 --text-*；确需字面量（大号数字时钟等）在同一行写 /* token-exempt: 原因 */。
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const root = join(import.meta.dirname, '..', 'src')
const violations = []

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full)
    else if (/\.(vue|css)$/.test(name) && !name.endsWith('tokens.css')) check(full)
  }
}

function styleRegions(file, text) {
  if (file.endsWith('.css')) return [{ offset: 0, body: text }]
  const regions = [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)]
    .map((match) => ({ offset: match.index + match[0].indexOf(match[1]), body: match[1] }))
  for (const match of text.matchAll(/\sstyle="([^"]*)"/g)) regions.push({ offset: match.index, body: match[1] })
  return regions
}

function check(file) {
  const text = readFileSync(file, 'utf8')
  for (const { offset, body } of styleRegions(file, text)) {
    for (const match of body.matchAll(/#[0-9a-fA-F]{3,8}\b|\brgb\(|font-size:\s*[0-9.]+px|\bfont:\s*[0-9.]+px/g)) {
      const lineNo = text.slice(0, offset + match.index).split('\n').length
      const lineText = text.split('\n')[lineNo - 1]
      if (match[0].startsWith('font') && /token-exempt:/.test(lineText)) continue
      violations.push(`${relative(root, file)}:${lineNo} ${match[0]}`)
    }
  }
}

walk(root)
if (violations.length) {
  console.error(`裸色值或字面字号 ${violations.length} 处，请改用 tokens.css 变量：\n${violations.join('\n')}`)
  process.exit(1)
}
console.log('design tokens: 0 literal colors or font sizes')
