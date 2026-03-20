import { describe, expect, test } from 'vitest'

import { applyCommunityThemeStyling, buildCommunityRoleAssignments } from '../src/components/graph3dTheme'

describe('graph3dTheme', () => {
  test('marks the strongest community hub as a core role', () => {
    const assignments = buildCommunityRoleAssignments(
      [
        { id: 'community:a', kind: 'community', label: 'Alpha', color: '#fb7185' },
        { id: 'community:b', kind: 'community', label: 'Beta', color: '#fb7185' },
        { id: 'community:c', kind: 'community', label: 'Gamma', color: '#fb7185' },
        { id: 'community:d', kind: 'community', label: 'Delta', color: '#fb7185' },
        { id: 'community:e', kind: 'community', label: 'Epsilon', color: '#fb7185' },
      ],
      [
        { id: 'ab', source: 'community:a', target: 'community:b', kind: 'similar', weight: 0.95 },
        { id: 'ac', source: 'community:a', target: 'community:c', kind: 'similar', weight: 0.9 },
        { id: 'ad', source: 'community:a', target: 'community:d', kind: 'similar', weight: 0.88 },
        { id: 'ae', source: 'community:a', target: 'community:e', kind: 'similar', weight: 0.84 },
        { id: 'bc', source: 'community:b', target: 'community:c', kind: 'similar', weight: 0.54 },
      ],
    )

    expect(assignments.get('community:a')?.role).toBe('core')
  })

  test('marks weak leaf communities as isolate roles', () => {
    const assignments = buildCommunityRoleAssignments(
      [
        { id: 'community:a', kind: 'community', label: 'Alpha', color: '#fb7185' },
        { id: 'community:b', kind: 'community', label: 'Beta', color: '#fb7185' },
        { id: 'community:c', kind: 'community', label: 'Gamma', color: '#fb7185' },
      ],
      [
        { id: 'ab', source: 'community:a', target: 'community:b', kind: 'similar', weight: 0.46 },
      ],
    )

    expect(assignments.get('community:a')?.role).toBe('isolate')
    expect(assignments.get('community:b')?.role).toBe('isolate')
    expect(assignments.get('community:c')?.role).toBe('isolate')
  })

  test('only recolors communities while keeping non-community semantic colors untouched', () => {
    const styled = applyCommunityThemeStyling(
      [
        {
          id: 'community:a',
          kind: 'community',
          label: 'Alpha transfer',
          color: '#fb7185',
        },
        {
          id: 'claim:1',
          kind: 'claim',
          label: 'Claim 1',
          color: '#fb923c',
        },
      ],
      [
        {
          id: 'similar:community:a->community:b',
          source: 'community:a',
          target: 'community:b',
          kind: 'similar',
          weight: 0.9,
          emphasis: 'primary',
        },
      ],
    )

    expect(styled.nodes.find((node) => node.id === 'community:a')?.color).not.toBe('#fb7185')
    expect(styled.nodes.find((node) => node.id === 'claim:1')?.color).toBe('#fb923c')
  })

  test('uses a brighter role palette for isolated communities', () => {
    const styled = applyCommunityThemeStyling(
      [
        {
          id: 'community:a',
          kind: 'community',
          label: 'Alpha transfer',
          color: '#fb7185',
        },
      ],
      [],
    )

    expect(styled.nodes.find((node) => node.id === 'community:a')?.color).toBe('#b35cc9')
  })
})
