import { afterEach, describe, expect, it, vi } from 'vitest'
import { takeCompleteSseFrames, createSseFrameQueue } from '../src/lib/sse-frame-batch.js'

describe('takeCompleteSseFrames', () => {
  it('splits on blank lines and keeps trailing partial', () => {
    const { frames, rest } = takeCompleteSseFrames('a\n\nb\r\n\r\nc')
    expect(frames).toEqual(['a', 'b'])
    expect(rest).toBe('c')
  })
})

describe('createSseFrameQueue', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('limits regular dispatch to maxPerSlice and reschedules', () => {
    vi.useFakeTimers()
    const seen = []
    const q = createSseFrameQueue((f) => seen.push(f), { maxPerSlice: 2 })
    q.push('one')
    q.push('two')
    q.push('three')
    q.push('four')

    expect(seen).toEqual([])
    vi.runOnlyPendingTimers()
    expect(seen).toEqual(['one', 'two'])
    expect(q.pending).toBe(2)
    vi.runOnlyPendingTimers()
    expect(seen).toEqual(['one', 'two', 'three', 'four'])
    expect(q.pending).toBe(0)
  })

  it('flush drains all frames synchronously', () => {
    const seen = []
    const q = createSseFrameQueue((f) => seen.push(f))
    q.push('one')
    q.push('two')
    q.flush()
    expect(seen).toEqual(['one', 'two'])
    expect(q.pending).toBe(0)
  })

  it('ignores blank frames', () => {
    const seen = []
    const q = createSseFrameQueue((f) => seen.push(f))
    q.push('  ')
    q.push('ok')
    q.flush()
    expect(seen).toEqual(['ok'])
  })
})
