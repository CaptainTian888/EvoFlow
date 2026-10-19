import { describe, expect, it, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { ToolApprovalPanel } from '../src/react/components/ToolApprovalPanel.tsx'

afterEach(() => cleanup())

describe('ToolApprovalPanel 决策态（多工具审批点击回执）', () => {
  it('默认渲染三个选项 + 确认按钮；点击确认回调所选 choice', () => {
    const seen: string[] = []
    render(<ToolApprovalPanel toolName="terminal" summary="rm -rf tmp" onConfirm={(c) => seen.push(c)} />)
    expect(screen.getByText('允许')).toBeTruthy()
    expect(screen.getByText('拒绝')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '确认' }))
    expect(seen).toEqual(['allow_once'])
    // 未进入决策态：面板仍可交互
    expect(screen.getByRole('button', { name: '确认' })).toBeTruthy()
  })

  it('decided=approved：面板切换为「已批准，等待执行…」结果条，不再渲染选项', () => {
    render(<ToolApprovalPanel toolName="write" summary="a.txt" decided="approved" onConfirm={() => {}} />)
    expect(screen.getByText('已批准，等待执行…')).toBeTruthy()
    expect(screen.queryByText('允许')).toBeNull()
    expect(screen.queryByRole('button', { name: '确认' })).toBeNull()
    expect(screen.getByText('a.txt')).toBeTruthy()
  })

  it('decided=denied：面板切换为「已拒绝」结果条', () => {
    render(<ToolApprovalPanel toolName="terminal" summary="ls" decided="denied" onConfirm={() => {}} />)
    expect(screen.getByText('已拒绝')).toBeTruthy()
    expect(screen.queryByText('允许')).toBeNull()
  })
})
