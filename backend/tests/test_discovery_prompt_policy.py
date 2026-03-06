from app.discovery.prompt_policy import (
    choose_prompt_variants,
    reset_prompt_policy_for_tests,
    update_prompt_policy_reward,
)


def test_rl_policy_explores_then_prefers_better_variant():
    reset_prompt_policy_for_tests()

    seen = set(choose_prompt_variants(domain="granular_flow", gap_type="gap_claim", top_k=1, method="rl_bandit"))
    seen.update(choose_prompt_variants(domain="granular_flow", gap_type="gap_claim", top_k=1, method="rl_bandit"))
    assert "base" in seen
    assert "optimized" in seen

    for _ in range(12):
        update_prompt_policy_reward(
            domain="granular_flow",
            gap_type="gap_claim",
            prompt_variant="optimized",
            reward=0.95,
            source="unit",
        )
        update_prompt_policy_reward(
            domain="granular_flow",
            gap_type="gap_claim",
            prompt_variant="base",
            reward=0.05,
            source="unit",
        )

    picks = [
        choose_prompt_variants(domain="granular_flow", gap_type="gap_claim", top_k=1, method="rl_bandit")[0]
        for _ in range(20)
    ]
    assert picks.count("optimized") >= 15


def test_non_rl_method_returns_deterministic_base_first():
    reset_prompt_policy_for_tests()
    out = choose_prompt_variants(domain="granular_flow", gap_type="gap_claim", top_k=2, method="heuristic")
    assert out[0] == "base"
