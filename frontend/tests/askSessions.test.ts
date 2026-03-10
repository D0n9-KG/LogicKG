import { describe, expect, test } from 'vitest'

import { readAskModuleStateFromStorage } from '../src/state/askSessions'
import { INITIAL_STATE, reducer } from '../src/state/store'

describe('ask session state', () => {
  test('migrates legacy single-session storage into a multi-session ask state', () => {
    const restored = readAskModuleStateFromStorage(
      JSON.stringify({
        draft: { question: 'Explain the method', k: 6 },
        currentId: 'turn-1',
        items: [
          {
            id: 'turn-1',
            question: 'What is the method?',
            k: 6,
            createdAt: 123,
            status: 'done',
            answer: 'It uses FEM.',
          },
        ],
      }),
    )

    expect(restored).not.toBeNull()
    expect(restored?.sessions).toHaveLength(1)
    expect(restored?.currentSessionId).toBe(restored?.sessions[0]?.id)
    expect(restored?.history).toHaveLength(1)
    expect(restored?.draftQuestion).toBe('Explain the method')
    expect(restored?.draftK).toBe(6)
    expect(restored?.sessions[0]?.history[0]?.question).toBe('What is the method?')
  })

  test('creates a new session and can switch back to an older session', () => {
    const seeded = reducer(INITIAL_STATE, {
      type: 'ASK_RESTORE',
      ask: readAskModuleStateFromStorage(
        JSON.stringify({
          version: 2,
          currentSessionId: 'session-a',
          sessions: [
            {
              id: 'session-a',
              title: 'Method discussion',
              createdAt: 111,
              updatedAt: 222,
              draft: { question: 'follow-up', k: 5 },
              currentId: 'turn-1',
              items: [
                {
                  id: 'turn-1',
                  question: 'What is the method?',
                  k: 5,
                  createdAt: 123,
                  status: 'done',
                  answer: 'It uses FEM.',
                },
              ],
            },
          ],
        }),
      )!,
    })

    const created = reducer(seeded, { type: 'ASK_CREATE_SESSION' })

    expect(created.ask.sessions).toHaveLength(2)
    expect(created.ask.currentSessionId).toBe(created.ask.sessions[0]?.id)
    expect(created.ask.history).toEqual([])
    expect(created.ask.currentId).toBeNull()
    expect(created.ask.draftQuestion).toBe('')
    expect(created.ask.draftK).toBe(8)

    const switched = reducer(created, { type: 'ASK_SWITCH_SESSION', sessionId: 'session-a' })

    expect(switched.ask.currentSessionId).toBe('session-a')
    expect(switched.ask.history).toHaveLength(1)
    expect(switched.ask.history[0]?.question).toBe('What is the method?')
    expect(switched.ask.currentId).toBe('turn-1')
    expect(switched.ask.draftQuestion).toBe('follow-up')
    expect(switched.ask.draftK).toBe(5)
  })

  test('deletes sessions and keeps ask state usable after removing the current session', () => {
    const seeded = reducer(INITIAL_STATE, {
      type: 'ASK_RESTORE',
      ask: readAskModuleStateFromStorage(
        JSON.stringify({
          version: 2,
          currentSessionId: 'session-b',
          sessions: [
            {
              id: 'session-a',
              title: 'Method discussion',
              createdAt: 111,
              updatedAt: 222,
              draft: { question: '', k: 5 },
              currentId: 'turn-1',
              items: [
                {
                  id: 'turn-1',
                  question: 'What is the method?',
                  k: 5,
                  createdAt: 123,
                  status: 'done',
                  answer: 'It uses FEM.',
                },
              ],
            },
            {
              id: 'session-b',
              title: 'Grounding',
              createdAt: 333,
              updatedAt: 444,
              draft: { question: 'next', k: 8 },
              currentId: 'turn-2',
              items: [
                {
                  id: 'turn-2',
                  question: 'Which chapter grounds it?',
                  k: 8,
                  createdAt: 345,
                  status: 'done',
                  answer: 'Chapter 1.',
                },
              ],
            },
          ],
        }),
      )!,
    })

    const deletedCurrent = reducer(seeded, { type: 'ASK_DELETE_SESSION', sessionId: 'session-b' })

    expect(deletedCurrent.ask.sessions).toHaveLength(1)
    expect(deletedCurrent.ask.currentSessionId).toBe('session-a')
    expect(deletedCurrent.ask.history[0]?.question).toBe('What is the method?')

    const deletedLast = reducer(deletedCurrent, { type: 'ASK_DELETE_SESSION', sessionId: 'session-a' })

    expect(deletedLast.ask.sessions).toHaveLength(1)
    expect(deletedLast.ask.currentSessionId).toBe(deletedLast.ask.sessions[0]?.id)
    expect(deletedLast.ask.history).toEqual([])
    expect(deletedLast.ask.currentId).toBeNull()
    expect(deletedLast.ask.draftQuestion).toBe('')
  })
})
