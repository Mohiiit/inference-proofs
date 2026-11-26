"""The kernel store on CPU: commit emits and builds once; a reply builds only when its own
emission added a kernel; the phases are reported apart. Every upstream process is
stub_upstream.py, whose emitters keep a store as cudagen.rs does."""

import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sash_fixtures import load, run_step

PROMPT = list(range(128))
TOK = list(range(1000, 1064))
# every flag an emission may pass: headline-c4096.sh's shared flags and head flags,
# sequence-job.sh's pins, the stub plan's line flags and step 5's own options
UPSTREAM_FLAGS = {"--round", "--numbits", "--z-hi-bits", "--variants", "--head-groups",
                  "--tight-table", "--kmax", "--ao-rem-bits", "--fold-rem-bits", "--fold-alpha",
                  "--table-bits", "--witness", "--block", "--min-blocks", "--families",
                  "--out", "--gkr-key-tiles", "--gkr-dequant", "--gkr-residual-stream",
                  "--gkr-freivalds", "--gkr-attnout"}  # fmt: skip


@pytest.fixture
def adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("IPROOFS_SASH_STUB_TOK", json.dumps(TOK))
    return load(tmp_path, monkeypatch)


def logged(adapter: ModuleType) -> list[dict[str, Any]]:
    path = adapter.host("/io/commands.jsonl")
    return [json.loads(ln) for ln in path.read_text().splitlines()]


def commands(adapter: ModuleType) -> list[list[str]]:
    return [c["argv"] for c in logged(adapter)]


def commit(adapter: ModuleType) -> dict[str, Any]:
    return run_step(adapter, "commit", model_dir="/models")


def prove(adapter: ModuleType, c: dict[str, Any], replies: int) -> dict[str, Any]:
    adapter.host("/io/prompts.jsonl").write_text((json.dumps(PROMPT) + "\n") * replies)
    return run_step(adapter, "prove", commitment_id=c["commitment_id"], model_dir="/models",
                    prover_files=c["prover_files"], prompts_file="/io/prompts.jsonl",
                    batch_size=1, batches=replies)  # fmt: skip


def phases(out: dict[str, Any]) -> dict[str, float]:
    return {p["name"]: p["seconds"] for p in out["phases"]}


def emitted(argvs: list[list[str]]) -> list[list[str]]:
    return [a for a in argvs if len(a) > 1 and a[1] in ("cudaemit", "genemit")]


def test_commit_emits_from_its_own_witness_and_builds_once(adapter: ModuleType) -> None:
    out = commit(adapter)
    argvs = commands(adapter)
    assert [a[0] for a in argvs].count("cargo") == 1
    emits = emitted(argvs)
    assert emits
    assert all("/io/state/commit-witness/" in a[a.index("--witness") + 1] for a in emits)
    # every emission precedes the build and read a dump that was there (the stub refuses a
    # dump whose directory is gone), and the witness was gone when the build ran
    tools = [a[0] for a in argvs]
    assert max(i for i, a in enumerate(argvs) if a in emits) < tools.index("cargo")
    assert all(c["exit_code"] == 0 for c in logged(adapter) if c["argv"] in emits)
    cargo = adapter.host("/io/stub-cargo.jsonl").read_text().splitlines()
    assert [json.loads(ln) for ln in cargo] == [{"commit_witness": False}]
    assert adapter.host("/io/state/build/kernels.done").read_text() == adapter.store()[2]
    assert list(phases(out)) == ["witness", "model_roots", "kernels_emit", "kernels_build"]
    assert out["commitment_id"] == adapter.commitment_of(out["verifier_files"])


def test_commit_emits_every_plan_line_and_widens_the_pins(adapter: ModuleType) -> None:
    """(a) the lines a reply emits, (b) every other plan line and the two pins sequence-job.sh
    passes, each widened only above its own value (the stub's pins: --ao-rem-bits 20, at the
    cap, and --fold-rem-bits 15); no flag upstream's drivers do not pass."""
    commit(adapter)
    emits = emitted(commands(adapter))
    plan_witnesses = {a[a.index("--witness") + 1] for a in emits}
    # 3 blocks of 2 layers and 2 heads: every segment's own witness is emitted from
    assert len(plan_witnesses) == 3 * 2 + 2
    folds = sorted({adapter.pinned(a, "--fold-rem-bits") for a in emits})
    assert folds == [15, 16, 17, 18, 19]
    assert {adapter.pinned(a, "--ao-rem-bits") for a in emits} == {20}
    flags = {t for a in emits for t in a[2:] if t.startswith("--")}
    assert flags <= UPSTREAM_FLAGS


def test_reply_whose_emission_adds_nothing_does_not_build(adapter: ModuleType) -> None:
    """The reply's lines name its own witness directory, which v1.0's key hashed; the store's
    content is what decides now."""
    c = commit(adapter)
    before = len(commands(adapter))
    out = prove(adapter, c, replies=2)
    argvs = commands(adapter)[before:]
    assert "cargo" not in [a[0] for a in argvs]
    emits = emitted(argvs)
    dirs = {re.search(r"/io/state/(witness-\d+)/", a[a.index("--witness") + 1]) for a in emits}
    assert {m.group(1) for m in dirs if m} == {"witness-0", "witness-1"}
    assert phases(out)["kernels_build"] == 0
    composed = [a for a in argvs if len(a) > 1 and a[1] == "compose-chunks"]
    assert len(composed) == 2
    assert {a[0] for a in composed} == {"/io/state/build/t-cuda/release/zk-prover"}


def test_reply_whose_emission_adds_a_kernel_builds_once(
    adapter: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = commit(adapter)
    shapes = adapter.store()
    before = len(commands(adapter))
    monkeypatch.setenv("IPROOFS_SASH_STUB_NEW", "f00dface")
    out = prove(adapter, c, replies=2)
    argvs = commands(adapter)[before:]
    tools = [a[0] for a in argvs]
    assert tools.count("cargo") == 1
    first_proof = next(i for i, a in enumerate(argvs) if len(a) > 1 and a[1] == "compose-chunks")
    assert tools.index("cargo") < first_proof  # built for the reply that needed it, before it
    after = adapter.store()
    assert (after[0] - shapes[0], after[1] - shapes[1]) == (1, 1)
    assert adapter.host("/io/state/build/kernels.done").read_text() == after[2]
    assert phases(out)["kernels_build"] > 0
    assert [p["proof_id"] for p in out["proofs"]] == ["req-0", "req-1"]


def test_prove_phases_apart(adapter: ModuleType) -> None:
    out = prove(adapter, commit(adapter), replies=1)
    assert list(phases(out)) == ["ids", "witness", "kernels_emit", "kernels_build", "prove"]


def test_prove_builds_when_no_build_was_installed(adapter: ModuleType) -> None:
    c = commit(adapter)
    adapter.host("/io/state/build/kernels.done").unlink()
    before = len(commands(adapter))
    prove(adapter, c, replies=1)
    assert [a[0] for a in commands(adapter)[before:]].count("cargo") == 1


def test_store_digest_keys_on_content_not_on_the_last_run(adapter: ModuleType) -> None:
    """cudagen.rs rewrites every store file byte for byte when no shape is new, except the two
    manifests, whose `source` (a witness path), `components` and new counts follow the last
    run; the install scripts read their `families`."""
    gen = adapter.host("/io/state/build/gen")
    gen.mkdir(parents=True)
    (gen / "shapes.json").write_text(
        json.dumps([["zk_row_eval", "a", {}], ["zk_key_eval", "b", {}]])
    )
    (gen / "gen_shapes.json").write_text(json.dumps([["zk_dequant_eval", "c", {}]]))
    (gen / "evaluate_zk_row_eval.cu").write_text("kernel")

    def manifest(source: str, new: int, families: list[str]) -> None:
        doc = {"source": source, "components": [{"component": source}], "families": families,
               "kernels": 2, "kernels_new_this_run": new}  # fmt: skip
        (gen / "manifest.json").write_text(json.dumps(doc))

    manifest("/io/state/witness-0/witness_B0_L0", 2, ["zk_row_eval", "zk_key_eval"])
    first = adapter.store()
    assert first[:2] == (2, 1)
    manifest("/io/state/witness-1/witness_B0_L0", 0, ["zk_row_eval", "zk_key_eval"])
    assert adapter.store() == first
    manifest("/io/state/witness-1/witness_B0_L0", 0, ["zk_row_eval"])
    assert adapter.store()[2] != first[2]
    manifest("/io/state/witness-0/witness_B0_L0", 2, ["zk_row_eval", "zk_key_eval"])
    (gen / "evaluate_zk_row_eval.cu").write_text("another kernel")
    assert adapter.store()[2] != first[2]


def test_a_store_with_no_kernel_stops_commit(
    adapter: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every emission refused: commit stops before the build rather than installing nothing."""
    monkeypatch.setattr(adapter, "emit", lambda *a, **k: (0, []))
    with pytest.raises(SystemExit, match="kernel store holds 0"):
        commit(adapter)
    assert "cargo" not in [a[0] for a in commands(adapter)]


def test_the_sweep_widens_each_line_from_the_pin_it_is_emitted_at(
    adapter: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared --ao-rem-bits 17 and a head pin of 12, which plan.py puts on the head lines
    after the shared one: the head lines are emitted at 12 and widened through 13..20, the
    layer lines at 17 and widened through 18..20, and no run reads a pin below its line's."""
    monkeypatch.setenv("IPROOFS_SASH_STUB_AO", "17")
    monkeypatch.setenv("IPROOFS_SASH_STUB_HEAD_AO", "12")
    commit(adapter)
    emits = emitted(commands(adapter))
    head = [a for a in emits if "/head_B" in a[a.index("--witness") + 1]]
    layer = [a for a in emits if a not in head]
    assert {adapter.pinned(a, "--ao-rem-bits") for a in head} == set(range(12, 21))
    assert {adapter.pinned(a, "--ao-rem-bits") for a in layer} == set(range(17, 21))
    # on a head line the shared pin stays as it is; only the value the prover reads moves
    assert all(a[a.index("--ao-rem-bits") + 1] == "17" for a in head)


def test_refused_lowerings_are_recorded_and_commit_completes(
    adapter: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("IPROOFS_SASH_STUB_EMIT_REFUSE", "--fold-rem-bits=18")
    commit(adapter)
    refused = [c for c in logged(adapter) if c["argv"] in emitted([c["argv"]]) and c["exit_code"]]
    assert refused
    assert {adapter.pinned(c["argv"], "--fold-rem-bits") for c in refused} == {18, 19}
    assert [a[0] for a in commands(adapter)].count("cargo") == 1
    assert re.search(r"--fold-rem-bits 16\.\.19 .*, \d+ refused", capsys.readouterr().err)


def test_every_generation_shape_refused_stops_commit_before_the_build(
    adapter: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IPROOFS_SASH_STUB_EMIT_REFUSE", "genemit")
    with pytest.raises(SystemExit, match="generation shapes; every emission was refused"):
        commit(adapter)
    assert "cargo" not in [a[0] for a in commands(adapter)]


def test_a_reply_partly_refused_proves_on_the_store_it_has(
    adapter: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = commit(adapter)
    before = len(commands(adapter))
    monkeypatch.setenv("IPROOFS_SASH_STUB_EMIT_REFUSE", "genemit")
    out = prove(adapter, c, replies=1)
    runs = logged(adapter)[before:]
    gen = [r for r in runs if r["argv"][1:2] == ["genemit"]]
    assert gen
    assert all(r["exit_code"] == 1 for r in gen)
    assert "cargo" not in [r["argv"][0] for r in runs]
    assert [p["proof_id"] for p in out["proofs"]] == ["req-0"]


def test_the_shape_set_is_the_same_for_one_set_reached_in_two_orders(adapter: ModuleType) -> None:
    """cudagen.rs keeps shapes in first-seen order, so the build key differs; the shape set
    does not, and it changes when a shape does."""
    gen = adapter.host("/io/state/build/gen")
    gen.mkdir(parents=True)

    def shapes(*irs: int) -> tuple[int, int, str, str]:
        rows = [["zk_attn_out_eval", f"seen{i}", {"ops": [ir]}] for i, ir in enumerate(irs)]
        (gen / "gen_shapes.json").write_text(json.dumps(rows))
        (gen / "shapes.json").write_text(json.dumps([["zk_row_eval", "a", {"ops": []}]]))
        return adapter.store()  # type: ignore[no-any-return]

    x_then_y, y_then_x = shapes(1, 2), shapes(2, 1)
    assert x_then_y[2] != y_then_x[2]
    assert x_then_y[3] == y_then_x[3]
    assert x_then_y[3].startswith("sha256:")
    assert shapes(1, 3)[3] != x_then_y[3]
