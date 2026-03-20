type ThemeableNode = {
  id: string
  kind: string
  label: string
  color: string
  auraColor?: string
  ringColor?: string
}

type ThemeableLink = {
  id: string
  source: string
  target: string
  kind: string
  weight: number
  emphasis?: 'default' | 'background' | 'primary' | 'focus'
  visible?: boolean
  displayColor?: string
}

type CommunityRole = 'core' | 'bridge' | 'focused' | 'isolate'

export type CommunityRoleAssignment = {
  role: CommunityRole
  baseColor: string
  auraColor: string
  ringColor: string
  degree: number
  strength: number
}

const ROLE_PALETTE: Record<CommunityRole, { base: string; aura: string; ring: string }> = {
  core: { base: '#4f7dff', aura: '#7da0ff', ring: '#d8e3ff' },
  bridge: { base: '#1ea89c', aura: '#67cbbf', ring: '#d2f1ec' },
  focused: { base: '#d69624', aura: '#ebb15b', ring: '#f7e4be' },
  isolate: { base: '#b35cc9', aura: '#cf8cdf', ring: '#eed8f4' },
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  if (value < min) return min
  if (value > max) return max
  return value
}

function hexToRgb(hex: string) {
  const normalized = hex.replace('#', '')
  const safe = normalized.length === 3 ? normalized.split('').map((part) => `${part}${part}`).join('') : normalized
  const value = Number.parseInt(safe, 16)
  return {
    r: (value >> 16) & 255,
    g: (value >> 8) & 255,
    b: value & 255,
  }
}

function rgbToHex(r: number, g: number, b: number) {
  const toHex = (value: number) => clamp(Math.round(value), 0, 255).toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

function mixHex(left: string, right: string, ratio: number) {
  const a = hexToRgb(left)
  const b = hexToRgb(right)
  const t = clamp(ratio, 0, 1)
  return rgbToHex(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t)
}

function rgba(hex: string, alpha: number) {
  const { r, g, b } = hexToRgb(hex)
  return `rgba(${r}, ${g}, ${b}, ${clamp(alpha, 0, 1)})`
}

function sortedCommunityIds<T extends ThemeableNode>(nodes: T[]) {
  return nodes
    .filter((node) => node.kind === 'community')
    .map((node) => node.id)
    .sort((left, right) => left.localeCompare(right))
}

function buildCommunityStats<T extends ThemeableNode, U extends ThemeableLink>(nodes: T[], links: U[]) {
  const communityIds = new Set(sortedCommunityIds(nodes))
  const stats = new Map<string, { degree: number; strength: number; maxWeight: number }>()

  for (const communityId of communityIds) {
    stats.set(communityId, { degree: 0, strength: 0, maxWeight: 0 })
  }

  for (const link of links) {
    if (link.kind !== 'similar') continue
    if (!communityIds.has(link.source) || !communityIds.has(link.target)) continue
    const weight = clamp(Number(link.weight) || 0, 0, 1)
    const sourceStats = stats.get(link.source)
    const targetStats = stats.get(link.target)
    if (sourceStats) {
      sourceStats.degree += 1
      sourceStats.strength += weight
      sourceStats.maxWeight = Math.max(sourceStats.maxWeight, weight)
    }
    if (targetStats) {
      targetStats.degree += 1
      targetStats.strength += weight
      targetStats.maxWeight = Math.max(targetStats.maxWeight, weight)
    }
  }

  return stats
}

export function buildCommunityRoleAssignments<T extends ThemeableNode, U extends ThemeableLink>(
  nodes: T[],
  links: U[],
): Map<string, CommunityRoleAssignment> {
  const stats = buildCommunityStats(nodes, links)
  const communityIds = sortedCommunityIds(nodes)
  const activeIds = communityIds.filter((communityId) => {
    const stat = stats.get(communityId)
    return (stat?.degree ?? 0) > 0
  })

  const assignments = new Map<string, CommunityRoleAssignment>()
  const isolatedIds = new Set<string>()
  for (const communityId of communityIds) {
    const stat = stats.get(communityId) ?? { degree: 0, strength: 0, maxWeight: 0 }
    const weakLeaf = stat.degree <= 1 && stat.strength <= 0.56
    if (stat.degree === 0 || weakLeaf) isolatedIds.add(communityId)
  }

  const rankedByStrength = [...activeIds]
    .filter((communityId) => !isolatedIds.has(communityId))
    .sort((left, right) => {
      const a = stats.get(left) ?? { degree: 0, strength: 0, maxWeight: 0 }
      const b = stats.get(right) ?? { degree: 0, strength: 0, maxWeight: 0 }
      const aScore = a.strength * 0.82 + a.degree * 0.18
      const bScore = b.strength * 0.82 + b.degree * 0.18
      return bScore - aScore || right.localeCompare(left)
    })

  const coreCount = activeIds.length >= 4 ? clamp(Math.round(activeIds.length * 0.18), 1, Math.max(1, activeIds.length - 2)) : 1
  const coreIds = new Set(rankedByStrength.slice(0, coreCount))

  const rankedByBridgeScore = rankedByStrength
    .filter((communityId) => !coreIds.has(communityId))
    .sort((left, right) => {
      const a = stats.get(left) ?? { degree: 0, strength: 0, maxWeight: 0 }
      const b = stats.get(right) ?? { degree: 0, strength: 0, maxWeight: 0 }
      const aConcentration = a.strength > 0 ? a.maxWeight / a.strength : 1
      const bConcentration = b.strength > 0 ? b.maxWeight / b.strength : 1
      const aBridgeScore = a.degree * (1 - aConcentration) + a.strength * 0.42
      const bBridgeScore = b.degree * (1 - bConcentration) + b.strength * 0.42
      return bBridgeScore - aBridgeScore || right.localeCompare(left)
    })

  const bridgeCount = activeIds.length >= 6 ? clamp(Math.round(activeIds.length * 0.24), 1, Math.max(1, activeIds.length - coreIds.size - 1)) : 1
  const bridgeIds = new Set(
    rankedByBridgeScore.filter((communityId) => (stats.get(communityId)?.degree ?? 0) >= 2).slice(0, bridgeCount),
  )

  for (const communityId of communityIds) {
    const stat = stats.get(communityId) ?? { degree: 0, strength: 0, maxWeight: 0 }
    const role: CommunityRole = isolatedIds.has(communityId)
      ? 'isolate'
      : coreIds.has(communityId)
        ? 'core'
        : bridgeIds.has(communityId)
          ? 'bridge'
          : 'focused'
    const palette = ROLE_PALETTE[role]
    assignments.set(communityId, {
      role,
      baseColor: palette.base,
      auraColor: palette.aura,
      ringColor: palette.ring,
      degree: stat.degree,
      strength: stat.strength,
    })
  }

  return assignments
}

export function applyCommunityThemeNodes<T extends ThemeableNode>(
  nodes: T[],
  assignments: Map<string, CommunityRoleAssignment>,
) {
  return nodes.map((node) => {
    if (node.kind !== 'community') return { ...node }
    const assignment = assignments.get(node.id)
    if (!assignment) return { ...node }
    return {
      ...node,
      color: assignment.baseColor,
      auraColor: mixHex(assignment.auraColor, '#ffffff', 0.06),
      ringColor: mixHex(assignment.ringColor, '#ffffff', 0.04),
    }
  })
}

export function applyCommunityThemeLinks<U extends ThemeableLink>(
  links: U[],
  assignments: Map<string, CommunityRoleAssignment>,
) {
  return links.map((link) => {
    if (link.kind !== 'similar') return { ...link }
    const left = assignments.get(link.source)
    const right = assignments.get(link.target)
    if (!left || !right) return { ...link }

    const mixed = mixHex(left.baseColor, right.baseColor, 0.5)
    const displayColor =
      link.emphasis === 'focus'
        ? rgba(mixHex(mixed, '#ffffff', 0.28), 0.9)
        : link.emphasis === 'primary'
          ? rgba(mixHex(mixed, '#ffffff', 0.08), 0.8)
          : undefined

    return {
      ...link,
      displayColor,
    }
  })
}

export function applyCommunityThemeStyling<T extends ThemeableNode, U extends ThemeableLink>(nodes: T[], links: U[]) {
  const assignments = buildCommunityRoleAssignments(nodes, links)
  const themedNodes = applyCommunityThemeNodes(nodes, assignments)
  const themedLinks = applyCommunityThemeLinks(links, assignments)

  return { nodes: themedNodes, links: themedLinks }
}
