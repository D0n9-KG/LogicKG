/* eslint-disable react-refresh/only-export-components */
// frontend/src/state/store.tsx
import { createContext, useContext, useReducer, useCallback, type ReactNode } from 'react'
import { derivePapersEntryGraph } from '../panels/papersPanelModel'
import { createAskSession, deleteAskSession, deriveAskModuleState, mapAskSession, prependAskSession, switchAskSession } from './askSessions'
import type { GlobalState, GlobalAction, ModuleId } from './types'

export const INITIAL_STATE: GlobalState = {
  activeModule: 'overview',
  graphElements: [],
  graphLayout: 'cose',
  layoutTrigger: 0,
  graphUpdateReason: 'replace',
  selectedNode: null,
  transitioning: false,

  papers: { selectedPaperId: null, searchQuery: '' },
  ask: deriveAskModuleState([createAskSession()], null),
  textbooks: { selectedTextbookId: null, selectedChapterId: null },
}

export function reducer(state: GlobalState, action: GlobalAction): GlobalState {
  switch (action.type) {
    case 'SET_MODULE': {
      const nextState: GlobalState = { ...state, activeModule: action.module, selectedNode: null }
      if (action.module !== 'papers') {
        return nextState
      }

      const entryGraphElements = derivePapersEntryGraph(state.graphElements, state.papers.selectedPaperId)
      if (!entryGraphElements || entryGraphElements === state.graphElements) {
        return nextState
      }

      return {
        ...nextState,
        graphElements: entryGraphElements,
        graphLayout: 'cose',
        layoutTrigger: state.layoutTrigger + 1,
        graphUpdateReason: 'replace',
        transitioning: false,
      }
    }
    case 'SET_GRAPH':
      if (state.graphElements === action.elements && state.graphLayout === action.layout) {
        return state
      }
      return {
        ...state,
        graphElements: action.elements,
        graphLayout: action.layout,
        layoutTrigger: state.layoutTrigger + 1,
        graphUpdateReason: 'replace',
      }
    case 'MERGE_GRAPH': {
      const existingIds = new Set(state.graphElements.map((e) => e.data.id))
      const newEls = action.elements.filter((e) => !existingIds.has(e.data.id))
      return {
        ...state,
        graphElements: [...state.graphElements, ...newEls],
        layoutTrigger: state.layoutTrigger + 1,
        graphUpdateReason: 'merge',
      }
    }
    case 'SET_SELECTED':
      return { ...state, selectedNode: action.node }
    case 'SET_TRANSITIONING':
      return { ...state, transitioning: action.value }
    case 'RELAYOUT':
      return { ...state, layoutTrigger: state.layoutTrigger + 1, graphUpdateReason: 'relayout' }

    case 'PAPERS_SELECT':
      return { ...state, papers: { ...state.papers, selectedPaperId: action.paperId } }
    case 'PAPERS_SEARCH':
      return { ...state, papers: { ...state.papers, searchQuery: action.query } }

    case 'ASK_SET_DRAFT':
      return {
        ...state,
        ask: mapAskSession(state.ask, action.sessionId, (session) => ({
          ...session,
          draftQuestion: action.question ?? session.draftQuestion,
          draftK: action.k ?? session.draftK,
          updatedAt: Date.now(),
        })),
      }
    case 'ASK_CREATE_SESSION':
      return {
        ...state,
        ask: prependAskSession(state.ask, createAskSession()),
      }
    case 'ASK_SWITCH_SESSION':
      return {
        ...state,
        ask: switchAskSession(state.ask, action.sessionId),
      }
    case 'ASK_DELETE_SESSION':
      return {
        ...state,
        ask: deleteAskSession(state.ask, action.sessionId),
      }
    case 'ASK_ADD_ITEM':
      return {
        ...state,
        ask: mapAskSession(state.ask, action.sessionId, (session) => ({
          ...session,
          title: session.title || action.item.question.slice(0, 42),
          history: [action.item, ...session.history].slice(0, 30),
          updatedAt: Date.now(),
        })),
      }
    case 'ASK_UPDATE_ITEM':
      return {
        ...state,
        ask: mapAskSession(state.ask, action.sessionId, (session) => ({
          ...session,
          history: session.history.map((item) => (item.id === action.id ? { ...item, ...action.patch } : item)),
          updatedAt: Date.now(),
        })),
      }
    case 'ASK_SET_CURRENT':
      return {
        ...state,
        ask: mapAskSession(state.ask, action.sessionId, (session) => ({
          ...session,
          currentId: action.id,
          updatedAt: Date.now(),
        })),
      }
    case 'ASK_RESET_SESSION':
      return {
        ...state,
        ask: mapAskSession(state.ask, action.sessionId, (session) => ({
          ...session,
          history: [],
          currentId: null,
          draftQuestion: action.keepDraft ? session.draftQuestion : '',
          draftK: action.keepDraft ? session.draftK : 8,
          updatedAt: Date.now(),
        })),
      }
    case 'ASK_RESTORE':
      return {
        ...state,
        ask: deriveAskModuleState(action.ask.sessions, action.ask.currentSessionId),
      }

    case 'TEXTBOOKS_SELECT':
      return { ...state, textbooks: { ...state.textbooks, selectedTextbookId: action.textbookId, selectedChapterId: action.chapterId } }

    default: {
      // TypeScript exhaustive check — if you add a new action to GlobalAction
      // and forget to handle it in the reducer, this will be a compile error.
      const _exhaustive: never = action
      return _exhaustive
    }
  }
}

type GlobalContextValue = {
  state: GlobalState
  dispatch: React.Dispatch<GlobalAction>
  switchModule: (module: ModuleId) => void
}

const GlobalContext = createContext<GlobalContextValue | null>(null)

export function GlobalStateProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE)

  const switchModule = useCallback((module: ModuleId) => {
    dispatch({ type: 'SET_TRANSITIONING', value: true })
    dispatch({ type: 'SET_MODULE', module })
    // Caller must dispatch SET_TRANSITIONING false after loading graph data
  }, [])

  return (
    <GlobalContext.Provider value={{ state, dispatch, switchModule }}>
      {children}
    </GlobalContext.Provider>
  )
}

export function useGlobalState() {
  const ctx = useContext(GlobalContext)
  if (!ctx) throw new Error('useGlobalState must be used inside GlobalStateProvider')
  return ctx
}

export function useModule() {
  return useGlobalState().state.activeModule
}
