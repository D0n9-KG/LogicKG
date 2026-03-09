/* eslint-disable react-refresh/only-export-components */
// frontend/src/state/store.tsx
import { createContext, useContext, useReducer, useCallback, type ReactNode } from 'react'
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
  ask: { history: [], currentId: null, draftQuestion: '', draftK: 8 },
  evolution: { selectedGroupId: null, searchQuery: '' },
  textbooks: { selectedTextbookId: null, selectedChapterId: null },
}

export function reducer(state: GlobalState, action: GlobalAction): GlobalState {
  switch (action.type) {
    case 'SET_MODULE':
      return { ...state, activeModule: action.module, selectedNode: null }
    case 'SET_GRAPH':
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
        ask: {
          ...state.ask,
          draftQuestion: action.question ?? state.ask.draftQuestion,
          draftK: action.k ?? state.ask.draftK,
        },
      }
    case 'ASK_ADD_ITEM':
      return { ...state, ask: { ...state.ask, history: [action.item, ...state.ask.history].slice(0, 30) } }
    case 'ASK_UPDATE_ITEM':
      return {
        ...state,
        ask: {
          ...state.ask,
          history: state.ask.history.map((item) => (item.id === action.id ? { ...item, ...action.patch } : item)),
        },
      }
    case 'ASK_SET_CURRENT':
      return { ...state, ask: { ...state.ask, currentId: action.id } }
    case 'ASK_RESET_SESSION':
      return {
        ...state,
        ask: {
          history: [],
          currentId: null,
          draftQuestion: action.keepDraft ? state.ask.draftQuestion : '',
          draftK: action.keepDraft ? state.ask.draftK : 8,
        },
      }
    case 'ASK_RESTORE':
      return {
        ...state,
        ask: {
          history: action.ask.history.slice(0, 30),
          currentId: action.ask.currentId,
          draftQuestion: action.ask.draftQuestion,
          draftK: action.ask.draftK,
        },
      }

    case 'EVOLUTION_SELECT_GROUP':
      return { ...state, evolution: { ...state.evolution, selectedGroupId: action.groupId } }
    case 'EVOLUTION_SEARCH':
      return { ...state, evolution: { ...state.evolution, searchQuery: action.query } }

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
