import { test, expect } from 'vitest'
import { relaxMarkdownLineBreaks, renderMarkdownStreaming } from '../src/lib/markdown.js'

test('case1: hashtag lines with # prefix merge into one line', () => {
  const raw = '官方活动标签（\n#ai新星计划\n#抖音前沿科技首发计划\n#抖音精选）拿流量扶持'
  const out = relaxMarkdownLineBreaks(raw)
  console.log('case1 input:', JSON.stringify(raw))
  console.log('case1 output:', JSON.stringify(out))
  console.log('case1 newline count:', (out.match(/\n/g) || []).length)
  expect(out).not.toMatch(/\n/)
})

test('case2: plain label lines without # prefix', () => {
  const raw = '官方活动标签（\nai新星计划\n抖音前沿科技首发计划\n抖音精选）拿流量扶持'
  const out = relaxMarkdownLineBreaks(raw)
  console.log('case2 input:', JSON.stringify(raw))
  console.log('case2 output:', JSON.stringify(out))
  console.log('case2 newline count:', (out.match(/\n/g) || []).length)
})

test('case3: URL split by blank line with #/account path', () => {
  const raw = '| 看板 | http://127.0.0.1:8787/ |\n\n#/account/test-123 |'
  const out = relaxMarkdownLineBreaks(raw)
  console.log('case3 input:', JSON.stringify(raw))
  console.log('case3 output:', JSON.stringify(out))
})

test('case4: full report snippet from user', () => {
  const raw = [
    '| 看板 | http://127.0.0.1:8787/ |',
    '#/account/%E5%B0%8F%E5%A4%A9fotos-969304610 |',
    '',
    '数据全景（18 条有效卡面数据）',
    '定位和你高度重合（AI 实战方法论、不卖课），他 14 万粉的打法：大厂热点工具首发实测（豆包/Seedance/Google I/O）+ 官方活动标签（',
    '#ai新星计划',
    '#抖音前沿科技首发计划',
    '#抖音精选）拿流量扶持',
  ].join('\n')
  const out = relaxMarkdownLineBreaks(raw)
  console.log('case4 input:\n', raw)
  console.log('case4 output:\n', out)
  const html = renderMarkdownStreaming(raw)
  console.log('case4 html:\n', html)
  expect(out).toContain('ai新星计划')
  expect(out).not.toMatch(/\nai新星计划/)
})