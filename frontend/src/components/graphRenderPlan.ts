import type { GraphUpdateReason } from '../state/types'

export type GraphRenderPlan = {
  animate: boolean
  animationDuration: number
  delayMs: number
  fadeBeforeSwap: boolean
}

export function resolveGraphRenderPlan(reason: GraphUpdateReason): GraphRenderPlan {
  if (reason === 'relayout') {
    return {
      animate: true,
      animationDuration: 260,
      delayMs: 70,
      fadeBeforeSwap: true,
    }
  }

  if (reason === 'merge') {
    return {
      animate: true,
      animationDuration: 160,
      delayMs: 0,
      fadeBeforeSwap: false,
    }
  }

  return {
    animate: false,
    animationDuration: 0,
    delayMs: 0,
    fadeBeforeSwap: false,
  }
}
