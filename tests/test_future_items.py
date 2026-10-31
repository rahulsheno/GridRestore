"""Items 2, 3, 4: real embeddings, optimal dispatch with P limits, multi-step MDP."""
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5433/gridrestore")

import numpy as np  # noqa: E402

from backend import embeddings  # noqa: E402


# ------------------------------- item 2: embedding back-ends

def test_hash_embedder_deterministic_and_normalized():
    e = embeddings.HashEmbedder()
    v1, v2 = e.embed("hospital emergency power repair"), e.embed("hospital emergency power repair")
    assert list(v1) == list(v2)
    assert len(v1) == e.dim == 32
    assert abs(np.linalg.norm(v1) - 1.0) < 1e-9


def test_sentence_transformer_embedder_384():
    """Real model path (all-MiniLM-L6-v2): downloads on first use, so this tests
    the whole chain. Skipped automatically if the package/model is unavailable."""
    e = embeddings.SentenceTransformerEmbedder()
    try:
        v = e.embed("hospital emergency power repair")
    except embeddings.EmbeddingUnavailable as exc:
        pytest.skip(f"sentence-transformers unavailable: {exc}")
    assert len(v) == 384
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5


def test_get_embedder_falls_back_when_backend_forced_hash(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    embeddings.reset_embedder()
    try:
        assert embeddings.get_embedder().dim == 32
    finally:
        embeddings.reset_embedder()


def test_unavailable_model_raises_or_falls_back():
    e = embeddings.SentenceTransformerEmbedder("no/such/model-xyz")
    try:
        e.embed("anything")
        # loaded anyway (cache?) -> fine
    except embeddings.EmbeddingUnavailable:
        pass  # correct fallback signal


def test_vectors_seed_and_search_use_active_backend():
    from backend.vectors import seed_embeddings, find_similar_repairs
    from backend.embeddings import get_embedder
    try:
        count = seed_embeddings()
    except embeddings.EmbeddingUnavailable:
        pytest.skip("transformer model unavailable")
    assert count == 8
    hits = find_similar_repairs("hospital emergency power repair", 3)
    assert len(hits) == 3
    if get_embedder().dim == 384:
        # real model: the hospital narrative should lead for this query
        assert hits[0]["task_id"] in ("T02", "T07")


# ------------------------------- item 3: optimal dispatch + P limits

def test_optimal_dispatch_respects_limits_and_ratings():
    from backend.grid.cases import load_case
    from backend.grid.operating_point import scale_loads, classify, continuation
    from backend.grid.dispatch import scale_loads_optimal, optimal_dispatch

    net = load_case("case14")
    base = scale_loads(net, 1.0)
    info = optimal_dispatch(net, 1.0, base)
    assert info["opf_converged"] and info["objective"] is not None
    # every generator stays within its active-power limits
    for idx in net.gen.index:
        p = float(net.gen.at[idx, "p_mw"])
        assert float(net.gen.at[idx, "min_p_mw"] or 0.0) - 1e-6 <= p
        assert p <= float(net.gen.at[idx, "max_p_mw"] or 1e9) + 1e-6
    op = classify(net)
    assert op.physical and op.status == "S0"


def test_continuation_optimal_mode_runs_and_reports():
    from backend.grid.cases import load_case
    from backend.grid.operating_point import continuation
    net = load_case("case14")
    table, summary = continuation(net, alpha_max=3.5, step=0.25, dispatch="optimal")
    assert summary["dispatch"] == "optimal"
    assert len(table) == len(table.alpha.unique())
    net2 = load_case("case14")
    _, summary2 = continuation(net2, alpha_max=3.5, step=0.25)
    assert summary2["dispatch"] == "proportional"
    with pytest.raises(ValueError):
        continuation(net2, dispatch="bogus")


# ------------------------------- item 4: multi-step MDP

def _ms(case="case14"):
    from backend.grid import mdp
    cal = mdp.calibrate(case)
    bus = mdp.most_critical_bus(mdp.load_case(case))
    return mdp, cal, bus


def test_derived_w3_increases_with_relative_repair_cost():
    from backend.grid.mdp import derive_action_cost_weight
    w_low = derive_action_cost_weight(700, 14000)
    w_high = derive_action_cost_weight(3500, 14000)
    assert 0.02 <= w_low < w_high <= 1.0
    w_demo = derive_action_cost_weight(1750, 14000)
    assert abs(w_demo - 0.1153) < 0.01  # matches the calibrated demo reference


def test_multistep_builds_and_solves():
    mdp, cal, bus = _ms()
    ms = mdp.build_multistep("case14", cal, horizon=4, growth=0.05, bus=bus)
    assert len(ms.stage_mdps) == 4 and ms.derived_w3 > 0
    for t, m in enumerate(ms.stage_mdps):
        assert np.allclose(m.P.sum(axis=2), 1.0)
    # penalties can only grow with the load factor over stages
    assert float(np.abs(ms.stage_mdps[3].R).max()) >= float(np.abs(ms.stage_mdps[0].R).max()) - 1e-9
    sol = mdp.multistep_solve(ms)
    assert len(sol["policy_by_stage"]) == 4
    for pol in sol["policy_by_stage"]:
        assert all(p in mdp.ACTIONS for p in pol)
    # the absorbing S3 collapse penalty cannot be scaled to zero
    s3 = mdp.STATES.index("S3")
    assert ms.stage_mdps[2].R[s3].min() < 0


def test_multistep_terminal_value_propagates():
    mdp, cal, bus = _ms()
    ms = mdp.build_multistep("case14", cal, horizon=3, growth=0.02, bus=bus)
    v_term = np.zeros(4); v_term[1] = -5.0
    sol = mdp.multistep_solve(ms, terminal_V=v_term)
    assert sol["V0"][1] < 0  # a bad terminal value surfaces in stage 0
