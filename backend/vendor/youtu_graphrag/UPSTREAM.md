# Upstream Source

- Repository: `https://github.com/TencentCloudADP/youtu-graphrag`
- Snapshot: `d982b5a8df1a269ee0e57a1d0ebd55feb719832c`
- Vendored on: `2026-03-11`

## Included Files

- `utils/tree_comm.py`
- `utils/call_llm_api.py`
- `utils/logger.py`

Only the TreeComm implementation and its direct runtime dependencies are vendored here.

## Local Adaptations

- Rewrote `utils` imports to package-relative imports so the code runs under `vendor.youtu_graphrag`.
- Kept `config.get_config()` optional; LogicKG passes TreeComm parameters from its own settings instead of vendoring the upstream config loader.
- Relaxed `LLMCompletionCall` initialization so missing API credentials do not break TreeComm clustering paths that never call the LLM naming helpers. `call_api()` still raises if invoked without a configured client.
