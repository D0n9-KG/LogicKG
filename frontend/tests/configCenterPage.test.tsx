import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'

const { apiGetMock, apiPostMock, apiPutMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
  apiPutMock: vi.fn(),
}))

vi.mock('../src/api', () => ({
  apiGet: apiGetMock,
  apiPost: apiPostMock,
  apiPut: apiPutMock,
}))

vi.mock('../src/pages/SchemaPage', () => ({
  default: () => <div>Schema Page</div>,
}))

import { I18nProvider } from '../src/i18n'
import ConfigCenterPage from '../src/pages/ConfigCenterPage'

const ASSISTANT_TURNS_KEY = 'logickg.config_center.assistant_turns.v1'
const LOCALE_KEY = 'logickg.ui.locale.v1'

describe('ConfigCenterPage discovery retirement', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.localStorage.setItem(LOCALE_KEY, 'en-US')
    window.localStorage.setItem(
      ASSISTANT_TURNS_KEY,
      JSON.stringify([
        {
          id: 'turn-1',
          created_at: '2026-03-12T10:00:00.000Z',
          goal: 'Tighten config',
          used_llm: false,
          suggestions: [
            {
              module: 'discovery',
              key: 'max_gaps',
              anchor: 'discovery.max_gaps',
              suggested_value: '6',
              rationale: 'Legacy suggestion',
            },
            {
              module: 'similarity',
              key: 'group_clustering_threshold',
              anchor: 'similarity.group_clustering_threshold',
              suggested_value: '0.91',
              rationale: 'Keep this one',
            },
          ],
        },
      ]),
    )

    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/config-center/profile') {
        return {
          profile: {
            version: 3,
            updated_at: '2026-03-12T10:00:00Z',
            modules: {
              similarity: {
                group_clustering_method: 'hybrid',
                group_clustering_threshold: 0.85,
              },
              runtime: {
                ingest_llm_max_workers: 3,
                phase1_chunk_claim_max_workers: 3,
                phase1_grounding_max_workers: 2,
                phase2_conflict_max_workers: 2,
                ingest_pre_llm_max_workers: 4,
                faiss_embed_max_workers: 3,
                llm_global_max_concurrent: 12,
              },
              providers: {
                llm_provider: 'deepseek',
                llm_api_key: '',
                llm_model: 'deepseek-chat',
              },
              llm_workers: {
                items: [],
              },
              infra: {
                neo4j_uri: 'bolt://localhost:7687',
                pageindex_enabled: false,
                textbook_chapter_max_tokens: 12000,
              },
              integrations: {
                crossref_mailto: '',
                crossref_user_agent: 'LogicKG/1.0',
              },
              community: {
                global_community_version: 'v1',
                global_community_max_nodes: 50000,
              },
            },
          },
        }
      }

      if (path === '/config-center/catalog') {
        return {
          modules: [
            { id: 'similarity', label: 'Similarity', fields: [] },
            { id: 'schema', label: 'Extraction Policy', fields: [], rule_keys: [], prompt_keys: [] },
            { id: 'runtime', label: 'Runtime Concurrency', fields: [] },
            {
              id: 'providers',
              label: 'Providers',
              fields: [
                {
                  key: 'llm_provider',
                  anchor: 'providers.llm_provider',
                  description: 'Choose the provider used for chat completions.',
                  current_value: 'deepseek',
                  type: 'select',
                  options: [
                    { value: 'deepseek', label: 'DeepSeek' },
                    { value: 'openai', label: 'OpenAI' },
                  ],
                },
                {
                  key: 'llm_api_key',
                  anchor: 'providers.llm_api_key',
                  description: 'API key for the selected LLM provider.',
                  current_value: '',
                  type: 'password',
                },
                {
                  key: 'llm_model',
                  anchor: 'providers.llm_model',
                  description: 'Default LLM model id.',
                  current_value: 'deepseek-chat',
                  type: 'string',
                },
              ],
            },
            {
              id: 'llm_workers',
              label: 'LLM Workers',
              description: 'Bind whole-paper extraction jobs to independently configured LLM gateways.',
              fields: [
                {
                  key: 'label',
                  anchor: 'llm_workers.label',
                  description: 'Worker display name.',
                  current_value: '',
                  type: 'string',
                },
                {
                  key: 'base_url',
                  anchor: 'llm_workers.base_url',
                  description: 'OpenAI-compatible base URL for this worker.',
                  current_value: '',
                  type: 'string',
                },
                {
                  key: 'api_key',
                  anchor: 'llm_workers.api_key',
                  description: 'API key used by this worker.',
                  current_value: '',
                  type: 'password',
                },
                {
                  key: 'model',
                  anchor: 'llm_workers.model',
                  description: 'Model override for this worker.',
                  current_value: '',
                  type: 'string',
                },
                {
                  key: 'max_concurrent',
                  anchor: 'llm_workers.max_concurrent',
                  description: 'Parallel paper slots for this worker.',
                  current_value: 3,
                  type: 'number',
                  min: 1,
                  max: 16,
                  step: 1,
                },
                {
                  key: 'enabled',
                  anchor: 'llm_workers.enabled',
                  description: 'Whether this worker can receive papers.',
                  current_value: true,
                  type: 'boolean',
                },
              ],
            },
            {
              id: 'infra',
              label: 'Infrastructure',
              fields: [
                {
                  key: 'neo4j_uri',
                  anchor: 'infra.neo4j_uri',
                  description: 'Neo4j connection string.',
                  current_value: 'bolt://localhost:7687',
                  type: 'string',
                },
                {
                  key: 'pageindex_enabled',
                  anchor: 'infra.pageindex_enabled',
                  description: 'Enable page index features.',
                  current_value: false,
                  type: 'boolean',
                },
                {
                  key: 'textbook_chapter_max_tokens',
                  anchor: 'infra.textbook_chapter_max_tokens',
                  description: 'Max tokens per textbook chapter chunk.',
                  current_value: 12000,
                  type: 'number',
                  min: 1000,
                  max: 64000,
                  step: 1000,
                },
              ],
            },
            {
              id: 'integrations',
              label: 'Integrations',
              fields: [
                {
                  key: 'crossref_mailto',
                  anchor: 'integrations.crossref_mailto',
                  description: 'Contact email for Crossref polite pool access.',
                  current_value: '',
                  type: 'string',
                },
                {
                  key: 'crossref_user_agent',
                  anchor: 'integrations.crossref_user_agent',
                  description: 'User-Agent header used for Crossref requests.',
                  current_value: 'LogicKG/1.0',
                  type: 'string',
                },
              ],
            },
            {
              id: 'community',
              label: 'Global Community',
              fields: [
                {
                  key: 'global_community_version',
                  anchor: 'community.global_community_version',
                  description: 'Community index version label.',
                  current_value: 'v1',
                  type: 'string',
                },
                {
                  key: 'global_community_max_nodes',
                  anchor: 'community.global_community_max_nodes',
                  description: 'Node cap for global community projection.',
                  current_value: 50000,
                  type: 'number',
                },
              ],
            },
          ],
        }
      }

      if (path === '/schema/active?paper_type=research') {
        return {
          schema: {
            paper_type: 'research',
            version: 8,
            name: 'balanced',
          },
        }
      }

      if (path === '/schema/versions?paper_type=research') {
        return {
          versions: [
            { version: 1, name: 'legacy' },
            { version: 8, name: 'balanced' },
          ],
        }
      }

      throw new Error(`Unexpected path: ${path}`)
    })

    apiPostMock.mockImplementation(async (path: string, payload?: unknown) => {
      if (path === '/config-center/assistant') return { used_llm: false, suggestions: [] }
      if (path === '/config-center/llm-workers/test') {
        const body = payload as { worker?: { base_url?: string } } | undefined
        if (body?.worker?.base_url === 'https://broken.example.com/v1') {
          return {
            reachable: false,
            error: '401 Unauthorized',
            worker: { id: 'worker-1', label: 'Gateway A' },
          }
        }
        return {
          reachable: true,
          error: null,
          worker: { id: 'worker-1', label: 'Gateway A' },
        }
      }
      if (path === '/schema/activate') {
        return {
          schema: {
            paper_type: 'research',
            version: Number((payload as { version?: number } | undefined)?.version ?? 8),
            name: 'balanced',
          },
        }
      }
      throw new Error(`Unexpected path: ${path}`)
    })
    apiPutMock.mockResolvedValue({
      profile: {
        version: 3,
        updated_at: '2026-03-12T10:00:00Z',
        modules: {
          similarity: {
            group_clustering_method: 'hybrid',
            group_clustering_threshold: 0.85,
          },
          runtime: {
            ingest_llm_max_workers: 3,
            phase1_chunk_claim_max_workers: 3,
            phase1_grounding_max_workers: 2,
            phase2_conflict_max_workers: 2,
            ingest_pre_llm_max_workers: 4,
            faiss_embed_max_workers: 3,
            llm_global_max_concurrent: 12,
          },
          providers: {
            llm_provider: 'openai',
            llm_api_key: 'sk-test',
            llm_model: 'gpt-4.1-mini',
            embedding_provider: 'openai',
            embedding_api_key: 'embed-test',
            embedding_model: 'text-embedding-3-small',
          },
          llm_workers: {
            items: [
              {
                id: 'worker-a',
                label: 'Gateway A',
                base_url: 'https://gw-a.example.com/v1',
                api_key: 'key-a',
                model: 'model-a',
                max_concurrent: 2,
                enabled: true,
              },
            ],
          },
          infra: {
            neo4j_uri: 'bolt://db.internal:7687',
            pageindex_enabled: true,
            textbook_chapter_max_tokens: 16000,
          },
          integrations: {
            crossref_mailto: 'ops@example.com',
            crossref_user_agent: 'LogicKG-Test/1.0',
          },
          community: {
            global_community_version: 'v2',
            global_community_max_nodes: 120000,
          },
        },
      },
    })
  })

  test('hides discovery tabs and stored discovery assistant anchors', async () => {
    render(
      <I18nProvider>
        <ConfigCenterPage />
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('Config Center')).toBeInTheDocument())

    expect(screen.queryByText('Discovery')).not.toBeInTheDocument()
    expect(screen.queryByText('discovery.max_gaps')).not.toBeInTheDocument()
    expect(screen.getAllByText('group_clustering_threshold').length).toBeGreaterThan(0)
    expect(screen.getByText('Runtime Concurrency')).toBeInTheDocument()
    expect(screen.getByText('LLM & Embeddings')).toBeInTheDocument()
    expect(screen.getByText('LLM Workers')).toBeInTheDocument()
    expect(screen.getByText('Infrastructure')).toBeInTheDocument()
    expect(screen.getByText('External Integrations')).toBeInTheDocument()
    expect(screen.getByText('Global Community')).toBeInTheDocument()
    expect(screen.getByText((text) => /Profile Format\s+v3/i.test(text))).toBeInTheDocument()
  })

  test('shows runtime controls and schema quick version switcher', async () => {
    render(
      <I18nProvider>
        <ConfigCenterPage />
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('Config Center')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Runtime Concurrency/i }))
    await waitFor(() => expect(screen.getByText('phase1_chunk_claim_max_workers')).toBeInTheDocument())
    expect(screen.getByText('ingest_llm_max_workers')).toBeInTheDocument()
    expect(screen.getByText('llm_global_max_concurrent')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Extraction Policy/i }))
    await waitFor(() => expect(screen.getByText('Schema Version Switcher')).toBeInTheDocument())
    expect(screen.getAllByText('balanced (v8)').length).toBeGreaterThan(0)

    const schemaSelects = screen.getAllByRole('combobox')
    fireEvent.change(schemaSelects[1], { target: { value: '8' } })
    fireEvent.click(screen.getByRole('button', { name: 'Activate Version' }))

    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith('/schema/activate', { paper_type: 'research', version: 8 }))
  })

  test('focuses providers on embeddings only', async () => {
    render(
      <I18nProvider>
        <ConfigCenterPage />
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('Config Center')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /LLM & Embeddings/i }))
    await waitFor(() => expect(screen.getByText('Embeddings')).toBeInTheDocument())
    expect(screen.queryByText('Default LLM')).not.toBeInTheDocument()
    expect(screen.queryByText('Compatibility / Fallback LLM')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('llm_provider')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('llm_api_key')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('llm_model')).not.toBeInTheDocument()
    expect(screen.getByText('Embeddings')).toBeInTheDocument()
    expect(screen.queryByLabelText('deepseek_api_key')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('openrouter_api_key')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('openai_api_key')).not.toBeInTheDocument()
  })

  test('keeps providers focused on embeddings even when workers are configured', async () => {
    const baseGet = apiGetMock.getMockImplementation()
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/config-center/profile') {
        return {
          profile: {
            version: 3,
            updated_at: '2026-03-12T10:00:00Z',
            modules: {
              similarity: {
                group_clustering_method: 'hybrid',
                group_clustering_threshold: 0.85,
              },
              runtime: {
                ingest_llm_max_workers: 3,
                phase1_chunk_claim_max_workers: 3,
                phase1_grounding_max_workers: 2,
                phase2_conflict_max_workers: 2,
                ingest_pre_llm_max_workers: 4,
                faiss_embed_max_workers: 3,
                llm_global_max_concurrent: 12,
              },
              providers: {
                llm_provider: 'deepseek',
                llm_api_key: '',
                llm_model: 'deepseek-chat',
                embedding_provider: 'openai',
                embedding_api_key: 'embed-test',
                embedding_model: 'text-embedding-3-small',
              },
              llm_workers: {
                items: [
                  {
                    id: 'worker-a',
                    label: 'Gateway A',
                    base_url: 'https://gw-a.example.com/v1',
                    api_key: 'key-a',
                    model: 'deepseek-chat',
                    max_concurrent: 3,
                    enabled: true,
                  },
                ],
              },
              infra: {
                neo4j_uri: 'bolt://localhost:7687',
                pageindex_enabled: false,
                textbook_chapter_max_tokens: 12000,
              },
              integrations: {
                crossref_mailto: '',
                crossref_user_agent: 'LogicKG/1.0',
              },
              community: {
                global_community_version: 'v1',
                global_community_max_nodes: 50000,
              },
            },
          },
        }
      }
      return baseGet?.(path)
    })

    render(
      <I18nProvider>
        <ConfigCenterPage />
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('Config Center')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /LLM & Embeddings/i }))
    await waitFor(() => expect(screen.getByText('Embeddings')).toBeInTheDocument())
    expect(screen.queryByLabelText('llm_provider')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Show Fallback LLM Settings/i })).not.toBeInTheDocument()
  })

  test('renders providers module and saves edited embedding values', async () => {
    render(
      <I18nProvider>
        <ConfigCenterPage />
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('Config Center')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /LLM & Embeddings/i }))
    await waitFor(() => expect(screen.getByLabelText('embedding_provider')).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText('embedding_provider'), { target: { value: 'openrouter' } })
    fireEvent.change(screen.getByLabelText('embedding_api_key'), { target: { value: 'embed-live-456' } })
    fireEvent.change(screen.getByLabelText('embedding_model'), { target: { value: 'text-embedding-3-large' } })

    fireEvent.click(screen.getByRole('button', { name: /Infrastructure/i }))
    await waitFor(() => expect(screen.getByLabelText('neo4j_uri')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('neo4j_uri'), { target: { value: 'bolt://db.internal:7687' } })
    fireEvent.click(screen.getByLabelText('pageindex_enabled'))

    fireEvent.click(screen.getByRole('button', { name: /External Integrations/i }))
    await waitFor(() => expect(screen.getByLabelText('crossref_mailto')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('crossref_mailto'), { target: { value: 'ops@example.com' } })

    fireEvent.click(screen.getByRole('button', { name: 'Save Profile' }))

    await waitFor(() =>
      expect(apiPutMock).toHaveBeenCalledWith(
        '/config-center/profile',
        expect.objectContaining({
          modules: expect.objectContaining({
            providers: expect.objectContaining({
              embedding_provider: 'openrouter',
              embedding_api_key: 'embed-live-456',
              embedding_model: 'text-embedding-3-large',
            }),
            infra: expect.objectContaining({
              neo4j_uri: 'bolt://db.internal:7687',
              pageindex_enabled: true,
            }),
            integrations: expect.objectContaining({
              crossref_mailto: 'ops@example.com',
            }),
          }),
        }),
      ),
    )
  })

  test('renders llm worker editor and saves worker rows', async () => {
    render(
      <I18nProvider>
        <ConfigCenterPage />
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('Config Center')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /LLM Workers/i }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Add Worker/i })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Add Worker/i }))

    fireEvent.change(screen.getByLabelText('Worker 1 Label'), { target: { value: 'Gateway A' } })
    fireEvent.change(screen.getByLabelText('Worker 1 Base URL'), { target: { value: 'https://gw-a.example.com/v1' } })
    fireEvent.change(screen.getByLabelText('Worker 1 API Key'), { target: { value: 'key-a' } })
    fireEvent.change(screen.getByLabelText('Worker 1 Model'), { target: { value: 'deepseek-chat' } })
    fireEvent.change(screen.getByLabelText('Worker 1 Parallel Papers'), { target: { value: '3' } })

    fireEvent.click(screen.getByRole('button', { name: 'Save Profile' }))

    await waitFor(() =>
      expect(apiPutMock).toHaveBeenCalledWith(
        '/config-center/profile',
        expect.objectContaining({
          modules: expect.objectContaining({
            llm_workers: {
              items: [
                expect.objectContaining({
                  label: 'Gateway A',
                  base_url: 'https://gw-a.example.com/v1',
                  api_key: 'key-a',
                  model: 'deepseek-chat',
                  max_concurrent: 3,
                  enabled: true,
                }),
              ],
            },
          }),
        }),
      ),
    )
  })

  test('tests llm workers and shows connectivity result inline', async () => {
    render(
      <I18nProvider>
        <ConfigCenterPage />
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('Config Center')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /LLM Workers/i }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Add Worker/i })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Add Worker/i }))
    fireEvent.change(screen.getByLabelText('Worker 1 Label'), { target: { value: 'Gateway A' } })
    fireEvent.change(screen.getByLabelText('Worker 1 Base URL'), { target: { value: 'https://gw-a.example.com/v1' } })
    fireEvent.change(screen.getByLabelText('Worker 1 API Key'), { target: { value: 'key-a' } })
    fireEvent.change(screen.getByLabelText('Worker 1 Model'), { target: { value: 'deepseek-chat' } })

    fireEvent.click(screen.getByRole('button', { name: /Test Worker 1/i }))

    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith(
        '/config-center/llm-workers/test',
        expect.objectContaining({
          worker: expect.objectContaining({
            label: 'Gateway A',
            base_url: 'https://gw-a.example.com/v1',
            api_key: 'key-a',
            model: 'deepseek-chat',
          }),
        }),
      ),
    )
    expect(screen.getByText('Connection OK')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Worker 1 Base URL'), { target: { value: 'https://broken.example.com/v1' } })
    fireEvent.click(screen.getByRole('button', { name: /Test Worker 1/i }))

    await waitFor(() => expect(screen.getByText('Connection failed: 401 Unauthorized')).toBeInTheDocument())
  })

  test('uses Chinese labels for config center modules in zh-CN locale', async () => {
    window.localStorage.setItem(LOCALE_KEY, 'zh-CN')

    render(
      <I18nProvider>
        <ConfigCenterPage />
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('配置中心')).toBeInTheDocument())

    expect(screen.getByText('模型与向量')).toBeInTheDocument()
    expect(screen.getByText('基础设施')).toBeInTheDocument()
    expect(screen.getByText('外部集成')).toBeInTheDocument()
    expect(screen.getByText('全局社区')).toBeInTheDocument()
    expect(screen.queryByText('Providers')).not.toBeInTheDocument()
    expect(screen.queryByText('Profile Format')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /模型与向量/i }))
    await waitFor(() => expect(screen.getByText('向量服务')).toBeInTheDocument())
    expect(screen.getByText('向量服务')).toBeInTheDocument()
    expect(screen.queryByText('默认 LLM')).not.toBeInTheDocument()
    expect(screen.queryByText('旧版专用密钥')).not.toBeInTheDocument()
    expect(screen.queryByText('默认提供方')).not.toBeInTheDocument()
    expect(screen.getByDisplayValue('提高抽取精度，同时减少噪声要点并保持召回稳定。')).toBeInTheDocument()
  })
})
