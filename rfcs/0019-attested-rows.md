# RFC-0019: Attested rows

- Authors: Mohiiit
- Created: 2026-11-26
- Requires: RFC-0002, RFC-0004, RFC-0005, RFC-0006, RFC-0008, RFC-0012, RFC-0015, RFC-0018
- Status: draft for discussion. Nothing here changes `levels/L1.yaml` or any stored record.

Normative text uses MUST, SHOULD, and MAY as defined in RFC 2119.

## Summary

This RFC defines an **attested row**: one system on one rung whose verifier accepts hardware attestation evidence (an Intel TDX quote, optionally with NVIDIA GPU Confidential Computing evidence) instead of a cryptographic proof. Attested rows run under the RFC-0005 adapter contract with `kind: attested`, carry a claim card, run the shared negative controls plus six attestation controls (A1 to A6), and report the same cost multiple and Fidelity figure as proving rows. They are printed in a separate band under each rung, are never ranked with proving rows, and never count toward the frontier. The purpose is the one PRD §10 names for v0.3, a "TEE attestation baseline": a reader who sees a proved reply cost 2,000 times serving can also see what a hardware-attested reply of the same model costs on the same GPU generation, and exactly which trust the proof removes.

## Motivation

1. **The roadmap asks for it.** PRD §10 lists "TEE attestation baselines" with "their own claim cards" for v0.3. Level 1 has no place for them: RFC-0018 SI-4b sends every system that "produces no proof (attestation, re-execution, dispute game, or fingerprint)" to the unrun list as `another kind of check`.
2. **Systems already wait in that list.** `web/_data/facts.json` records Private ML SDK ("a hardware signature over the SHA-256 hashes of the HTTP request and response bodies rather than generating a cryptographic proof") and Tinfoil ("relies on hardware enclave attestation") under that reason. They are the class of system providers deploy today for verifiable inference, and the benchmark currently says nothing about them beyond their absence.
3. **The cost multiple lacks its middle point.** RFC-0015 gives every rung two ends: serving (no assurance) and recompute (full assurance for a verifier holding the weights). Between them sits the option a relying party most often weighs against a proof: trust the CPU and GPU vendors, pay close to serving cost. Without an attested row the reader cannot see what the extra multiple of a proof buys.
4. **The six checks cannot tell the two apart.** RFC-0018 SI-4 already records that `systems/fake` passes all six checks with a keyed hash. An attested system built honestly would also pass them. This is why attested rows must be shown, labelled for what they are, and kept out of the ranking, rather than left unmeasured.
5. **The site names a gap attestation can address.** The site's "What a proof shows" page says a proof "does not ... prove that the reply was served live" (`web/llms.txt` L90). An attestation over a harness challenge, produced while the reply is served, is a statement about a live serving process. This RFC records that statement precisely without claiming more for it.

## Goals

- Define `kind: attested` adapters whose `commit`, `prove`, and `verify` steps map onto the RFC-0005 contract without new subcommands.
- Keep AGENTS.md rule 6 intact: every expected measurement, root certificate, collateral snapshot, and challenge the verifier checks comes from the harness record, never from the evidence the prover returns.
- Keep verification offline (`--network none`, INV-ADAPTER-4) by having the harness capture collateral outside the container and pass it in as a pinned verifier file.
- Give attestation evidence a claim card under the existing `claim/1` schema, copied from the publisher's documentation, with the trust placed in hardware vendors written into `assumptions` and `residual`.
- Add controls that exercise the parts of an attestation verifier the shared suite does not reach: measurement policy, certificate chain, TCB policy, freshness, debug mode, and GPU evidence.
- Report the same cost multiple (RFC-0018 §Cost) and Fidelity figure (SI-9), so attested and proved rows of one rung share axes.
- Never rank an attested row, never place it above or between proving rows, and never let it set the frontier.

## Non-Goals

- Building, operating, or certifying a TEE serving system. The benchmark runs a publisher's system at a public pin, as it does for provers (PRD §5).
- Testing hardware security: side channels, physical attacks, firmware compromise, or vendor key compromise. No control here attempts them, and the site says so (as RFC-0018 says of forgery).
- Grading vendors, CPU generations, or cloud providers.
- Comparing an attested row's assurance with a proving row's on one scale. The claim card and glyph state each; nothing combines them.
- Changing Level 1. `levels/L1.yaml` is frozen (LV-1). Attested rows enter in a later level or as an annex the owner decides on (Q6).
- AMD SEV-SNP, Arm CCA, AWS Nitro and other TEEs. The design is written for Intel TDX plus NVIDIA CC because that is what the listed systems use; other TEEs need their own amendment (Q5).

## Proposed Design

### Terms

- **Evidence.** What an attested prover returns per request: a TDX quote and, when the system claims GPU protection, NVIDIA GPU attestation evidence. Stored as proof parts under `/io/proofs/<proof_id>/` and named "evidence" on pages (as RFC-0015 REF-2 names reference outputs "outputs").
- **Measurement set.** The values that identify the trusted computing base the evidence speaks for. For TDX: `MRTD`, `RTMR0` to `RTMR3` (48-byte SHA-384 registers), `TD_ATTRIBUTES` (including the `DEBUG` bit), `XFAM`, and `MRCONFIGID`, `MROWNER`, `MROWNERCONFIG` when the system uses them. For NVIDIA CC: the GPU's reported measurements and driver and VBIOS versions as the publisher's verifier exposes them.
- **Report data.** The 64-byte `REPORTDATA` field the TD writes into its quote. It is the only place a TDX quote can carry the request, the reply, the commitment, and the challenge.
- **Collateral.** Intel's signed TCB info, QE identity, and certificate revocation lists, plus NVIDIA's equivalent when GPU evidence is checked. Collateral changes over time and carries `issueDate` and `nextUpdate`.
- **TCB status.** The status DCAP verification returns for a platform: `UpToDate`, `SWHardeningNeeded`, `ConfigurationNeeded`, `ConfigurationAndSWHardeningNeeded`, `OutOfDate`, `OutOfDateConfigurationNeeded`, or `Revoked`.
- **Challenge.** A 32-byte value the harness draws for each request of each session and passes to `prove`, which the evidence must bind.

### What an accepted attestation establishes

An accepted attested row states, at most:

> A platform whose certificate chain ends at the vendor root the harness pinned, with TCB status inside the policy the harness pinned, ran a trust domain whose measurement set equals the one recorded at `commit`, and that trust domain wrote report data binding this commitment, this request, this reply, and this challenge.

Whether that means "the reply is the committed model's greedy reply" depends on what the measured code does. That is a statement the publisher makes about its code, not one the evidence proves. It is recorded the same way RFC-0018 SI-4a records it for provers: `level_statement.accept_is_model_reply` in `properties.yaml`, with pinned quotes, or a `note` and "read as" when no single sentence states it.

### system.yaml

`kind` gains the value `attested`. An attested system adds one block:

```yaml
# systems/<name>/system.yaml (shape, additions only)
kind: "attested"
attestation:
  cpu_tee: "intel-tdx"                # only value in this RFC (Q5)
  gpu_tee: "nvidia-cc" | "none"       # "none": the claim card MUST say the GPU is outside the TCB
  quote_versions: [4, 5]              # as upstream documents
  verifier:                            # the program `verify` runs, upstream's own where it ships one
    repo: "<owner>/<repo>"
    commit: "<40 hex>"
  measurement_source: "reproducible-build" | "publisher-manifest" | "first-run"
  report_data_layout: "<SourceRef to upstream's definition>"
  tcb_policy: ["UpToDate"]            # statuses `verify` accepts; Q2
```

- ATT-1. `attestation.verifier` MUST be a standalone verifier that checks stored evidence against harness-supplied inputs, as for any system (RFC-0018 SI-4b `no public verifier`). A verifier that only runs inside the prover process, or only calls a vendor web service, does not qualify (Q3).
- ATT-2. `measurement_source` records where the expected measurement set comes from, and is printed on the system page:
  - `reproducible-build`: the publisher documents how to rebuild the TD image and compute its measurements; the harness rebuilds it at `setup` from the pin and computes the expected set itself. This is the only source under which the measurement is checked against code.
  - `publisher-manifest`: the publisher ships the expected values at the pin; the harness copies them with their source link.
  - `first-run`: neither exists; the harness records the set observed in the first counted session. This is trust on first use, and the claim card's `residual` MUST say so.
- ATT-3. `report_data_layout` MUST link to the publisher's own definition of how report data is computed. The adapter MUST NOT define a layout of its own (INV-ADAPTER-1). If upstream binds HTTP bodies rather than token ids (as Private ML SDK does), the adapter README documents the mapping from the request's token ids to the bytes upstream hashes, and A-controls test it.

### Steps

| Step | Attested adapter does | Harness records |
|---|---|---|
| `setup` | Builds or loads the pinned TD image and serving stack. Under `reproducible-build`, computes the expected measurement set. | Image digest, computed measurement set |
| `commit` | Hashes the model files, writes the expected measurement set and the TCB policy as verifier files. `commitment_id = sha256(model_digest ‖ measurement_set_digest ‖ policy_digest)`. | `commitment_id`, verifier files, plus the collateral snapshot it captured itself (ATT-5) |
| `prove` | Serves each request inside the TD with the challenge for that request, returns the reply and its evidence as proof parts. | Release times, evidence digests |
| `verify` | Runs `attestation.verifier` on the evidence with the commit record, collateral snapshot, request, claimed reply, and challenge. No GPU, no network, no weights. | Verdict, reason code, TCB status, collateral dates |

- ATT-4. **Challenge.** For `kind: attested`, `job.json` for `prove` and `verify` carries `challenges`: one 32-byte hex value per request, `sha256("iproofs/challenge/1" ‖ run_id ‖ session_slot ‖ request_index ‖ control_seed)`. `verify` receives the challenge from the harness record, never from the evidence. Proving systems ignore the field. This is an additive change to the adapter job schema (RFC-0012), so the schema version goes up.
- ATT-5. **Collateral.** The harness, not the container, fetches collateral from the vendor's public endpoints at `commit` time, records its digest, `issueDate`, `nextUpdate` and source URL in the run manifest, and copies it into the `verify` I/O directory as a verifier file. `verify` evaluates the evidence as of a fixed `verification_time` equal to the collateral capture time. This keeps `--network none` (INV-ADAPTER-4), makes `verify` deterministic, and lets anyone rerun it later on the stored bytes.
- ATT-6. **Fail closed.** `verify` MUST return `reject` when any of these hold, and the adapter maps the verifier's reason to the `reason` field so controls can tell why: signature or chain invalid; chain root differs from the pinned root; TCB status outside `tcb_policy`; any PCK or TCB signing certificate on a pinned CRL; `DEBUG` set in `TD_ATTRIBUTES`; any measurement differs from the commit record; report data differs from the value recomputed from the harness inputs; GPU evidence missing or failing when `gpu_tee` is not `none`. Collateral whose `nextUpdate` is earlier than `verification_time` yields `invalid_call` with reason `stale_collateral`, never `accept`.
- ATT-7. **Weights stay outside the verifier.** `verify` never reads model files (the existing Verify without weights check applies unchanged). An attested system that needs the weights to verify is not attested in the sense of this RFC.

RISK: the harness timing model assumes the harness runs outside the prover container on the same host. For a TDX system the serving stack runs inside a trust domain, so the harness either runs inside the TD guest (and is therefore inside the measured boundary it is timing) or talks to the TD over a local channel. Plan: allow both; record which one in the manifest as `attestation.harness_location: guest | host`; time from the harness side in both cases, and treat any channel latency as part of the prove scope, which only makes the attested multiple larger.

### Controls

All shared controls (RFC-0008) apply unchanged, generated by the harness from the stored evidence and records:

| Id | What it reaches in an attested verifier |
|---|---|
| C1, C2 | report data no longer matches the recomputed binding for the altered reply or prompt |
| C3 | the commitment digest in the commit record differs, so the binding differs |
| C4, C7 | the binding names a different request |
| C5, C6, C8 | quote or certificate parsing and signature checks |
| P1 | holds only if the measured code hashes the weights it loads into the binding; the README states whether upstream does, and P1 records the outcome either way |
| P2 | as P1, for precision |

Attestation controls, registered for every `kind: attested` system:

| Id | Construction | Expected | Hardware |
|---|---|---|---|
| A1 | Verify honest evidence against a commit record with one byte changed in one RTMR (each register, seeded) | `reject` | none |
| A2 | Re-sign the quote with a freshly generated chain that mirrors the vendor chain's subject names | `reject` | none |
| A3 | Verify honest evidence with the next session's challenge | `reject` | none |
| A4 | Verify honest evidence against collateral that marks the platform outside `tcb_policy`, using a real archived collateral set for that platform where one exists | `reject` | none, needs an archived set (RISK below) |
| A5 | Serve one request from a TD launched with `DEBUG` set, otherwise identical | `prover_failed` or `reject` | TDX host |
| A6 | When `gpu_tee` is not `none`: drop the GPU evidence, then swap in GPU evidence from another request | `reject` on both | none |

- ATT-8. Each A-control trial runs with an honest twin, as every RFC-0008 trial does, and is `void` if the twin is not accepted.
- ATT-9. A-controls record the verifier's `reason` alongside the verdict. A `reject` for the wrong reason (for example A1 rejected because parsing failed, not because the measurement differed) is recorded as `reject` with `reason_mismatch: true` and listed on the system page. It does not change the check state; it tells the reader which check actually fired.
- ATT-10. A working accept on any A-control follows RFC-0008 §Disclosure: private report to the publisher first.

RISK: A4 needs collateral that Intel signed and that marks a real platform outside policy. Editing current collateral breaks its signature and tests the wrong thing. Plan: use an archived collateral set from before a published TCB recovery for the same platform family, captured once and stored by digest; when none exists, A4 is `not_applicable` with that reason, never constructed by editing.

### Claim card

Attested rows use `claim/1` unchanged and follow every rule of RFC-0002, including "copy, do not infer". The mapping below says where attestation facts go; every value is still copied from the publisher or written `not stated`.

| Field | Where attestation facts go |
|---|---|
| `relation` | The publisher's sentence on what acceptance means |
| `security.notion.kind` | `other`, with the publisher's description (as RFC-0002 Q2 already does for statistical guarantees) |
| `security.level` | What the publisher states, usually `not stated`; the benchmark never derives a bit level for a TEE |
| `security.setup` | As stated; a vendor root of trust is recorded in `assumptions`, not translated into `trusted` by us |
| `zero_knowledge` | As stated; weights hidden from the verifier is not zero knowledge unless the publisher says so |
| `assumptions` | Vendor roots, the TCB policy, measurement source (ATT-2), whether the GPU is inside the TCB |
| `binding` | Per-edge table from the publisher's report data layout: prompt, reply, commitment, challenge |
| `residual` | As stated; a reviewer checklist (Q4) asks whether the publisher addresses physical access, side channels, and vendor key compromise, and records `not stated` where it does not |

`claim_class` keeps its three tokens. Attested rows are told apart by `kind`, not by the class string, so targets (RFC-0009) can filter on either.

### Glyph

The five petals are computed by the existing rules (RFC-0018 GL-1, GL-2) from `properties.yaml` and the runs. No petal is added or reinterpreted for attested rows. In practice, for the systems listed today: Integrity requires a proved soundness bound and is expected to read `Not stated`; Trust assumptions is expected to read `Not met` where the publisher names a vendor; Fidelity comes from the run and can be `Met`, since attested systems usually serve the publisher's release precision. These are expectations to check against the board, not rules.

A system page for an attested row adds one depth-3 block, **Attestation**, listing the measurement set and its source (ATT-2), the TCB policy, collateral capture date and `nextUpdate`, `harness_location`, and whether the GPU is inside the TCB. The block sets no state.

### Cost

- ATT-11. The cost multiple is computed by the existing derivation (RFC-0018 §Cost) with no new formula: steady GPU-seconds per further attested reply over the rung's serving baseline.
- ATT-12. Attested rows run on their own hardware profile, `attested-<gpu>-cc`, with GPU Confidential Computing on and the CPU in TDX mode, recorded by the host probe. RFC-0006 Q4 (CC off for every H200 run) is amended to apply to proving and reference profiles only. The serving baseline stays the CC-off `ref-serve` row, so the multiple includes the full cost of running confidential: TD overhead, encrypted CPU to GPU transfers, attestation generation.
- ATT-13. Time to produce evidence is reported as its own measured figure (`attest` scope inside `prove`), when the adapter can mark it, using the generation marks of RFC-0018 AD-4.

### Display and ranking

- ATT-14. An attested row never receives a position, never counts toward the frontier (OR-6), and never sits between two proving rows. On each rung it appears in a band under the proving rows titled "Attested, not proved", with the same figure columns.
- ATT-15. An attested row's standing uses the existing words with "attested" in place of "passed": "Attested: all six checks held", "Not attested: <Check> check failed", "Not attested yet: <Check> check not decided".
- ATT-16. The Overview plot (SI-7) MAY draw attested rows on the same axes, with a mark distinct from both passed and not-passed proving rows. It never joins an attested mark to a proving one.
- ATT-17. A system listed under `another kind of check` keeps that reason on the ladder's unrun list until it has an attested row; it then moves to the attested band. The precedence order of SI-4b is unchanged.

### Failure modes

| Failure | Response |
|---|---|
| No TDX host, or CC cannot be enabled on the profile | Job fails with `environment`; no row; reason printed |
| Collateral fetch fails at `commit` | Job fails with `environment` before `prove`; nothing is attested without collateral |
| Collateral expires between `commit` and a later `verify` rerun | `invalid_call`, `stale_collateral`; the original verdict stands in the stored run |
| Observed measurement differs from the reproducible build | `verify` rejects (ATT-6); the session is recorded as failed, the difference is printed |
| Publisher ships no standalone verifier | `no public verifier` on the unrun list, as today |
| Upstream report data binds less than prompt, reply and commitment | Recorded in the claim card's `binding` as `absent`; the corresponding check fails or is undecided by the existing rules |
| Platform TCB status changes during a campaign | Each run records the status it saw; runs outside policy fail; no rerun is selected after seeing results |

## Alternatives Considered

1. **Treat attested systems as reference rows (RFC-0015).** Reference rows have no claim card, no verifier, and no controls. An attested system has all three, and dropping them would hide exactly what a reader needs. Rejected.
2. **Rank attested rows with proving rows.** The six checks cannot distinguish the two (SI-4), so a ranking would put a vendor-trust statement next to a cryptographic one under one order. That is the comparison hazard RFC-0002 exists to prevent. Rejected.
3. **Build our own attested serving stack (for example vLLM in a TD).** It would give a clean baseline on every rung, but the benchmark would then be grading its own system, which PRD §5 rules out. Kept as Q7, for a `ref-` adapter if no publisher system covers a rung.
4. **Verify through a vendor attestation service (Intel Trust Authority, NVIDIA NRAS).** Simpler for adapters, but it needs network at `verify`, adds a third party to every verdict, and cannot be rerun on stored bytes. Rejected for `verify`. A publisher that relies on one records it as an assumption, and the benchmark still verifies locally.
5. **Accept the measurement the evidence reports and print it.** This is the TEE form of the DeepProve problem (a verifier key read from the proof file): the verifier would accept whatever code ran. Rejected by ATT-2 and AGENTS.md rule 6.

## Drawbacks

- Attested rows need TDX hosts with CC-capable GPUs, a hardware class separate from the current H200 profiles.
- Collateral makes `verify` depend on a capture time, and a rerun after `nextUpdate` cannot reproduce `accept`. The stored verdict stands, but tier `reproduced` (RFC-0007) needs a rule for this (Q8).
- Most publishers do not ship reproducible TD builds, so many rows will start at `first-run` measurements, a weak form that the page must explain plainly.
- A band of rows at close to 1× serving under rows at thousands of times serving can be read as "attestation wins". The band title and claim cards carry the difference; that may not be enough on its own.

## Migration / Rollout

1. No stored record, release, or level file changes. Level 1 v1.0 is untouched.
2. Schemas: `system/1` adds `kind: attested` and the `attestation` block (version bump under RFC-0012); the adapter job schema adds optional `challenges`; `controls/1` adds IDs A1 to A6; the manifest adds the collateral record and `attestation.harness_location`. `claim/1` and `properties/2` are unchanged.
3. RFC-0006 Q4 is amended as in ATT-12.
4. `systems/fake-attested`: a CPU-only adapter that signs a fake quote with a test root, so the whole path, including A1 to A4 and A6, runs in CI with no TDX host.
5. First real candidate: a system already on the unrun list with `another kind of check` whose publisher ships a standalone verifier, after an issue with the publisher (systems/README.md §1).
6. Attested rows appear from the first release of the level the owner chooses (Q6).

## Testing Strategy

Unit and schema (CPU, CI):

- `test_system_attested_schema`: valid `kind: attested` examples pass; a missing `attestation.verifier` or a `measurement_source` outside the enum fails.
- `test_challenge_derivation`: a hand-computed challenge for a fixed `run_id`, slot, index and seed matches.
- `test_verify_inputs_from_record`: a `prove` step that writes a forged measurement set and challenge into its evidence directory does not change what `verify` receives (extends `test_commitment_from_harness_record`).
- `test_collateral_offline`: `verify` runs under `--network none` with the captured collateral; removing the collateral file yields `invalid_call`.
- `test_stale_collateral`: `verification_time` after `nextUpdate` yields `invalid_call`, `stale_collateral`.

Fixture (CPU, `systems/fake-attested`, and every real attested adapter on captured evidence):

- `test_a1_each_rtmr`: one changed byte in each of `MRTD` and `RTMR0` to `RTMR3` rejects with a measurement reason.
- `test_a2_foreign_chain`: a mirrored chain rejects with a chain reason.
- `test_a3_next_challenge`: honest evidence with the next challenge rejects with a binding reason.
- `test_a6_gpu_evidence`: dropped and swapped GPU evidence both reject.
- `test_reason_mismatch_flag`: a control rejected for an unexpected reason is recorded with `reason_mismatch: true` and the same verdict.

GPU host:

- One counted session per rung on `attested-<gpu>-cc`, with the host probe confirming TDX and CC on.
- A5 on the same host.
- P1 and P2 on the same host.

## Decisions

Proposed, for the owner to accept, change or reject.

- Q1. Attested rows are a row class, not a new level: they live beside proving rows on the same rungs and request.
- Q2. `tcb_policy` defaults to `["UpToDate"]`. A publisher that documents a wider policy is run under its documented policy, and the system page prints it.
- Q3. A verifier that only calls a vendor web service does not count as a public verifier (Alternative 4).
- Q4. Claim cards for attested rows are reviewed against a fixed checklist: vendor roots, TCB policy, measurement source, GPU in or out of the TCB, report data layout, physical access, side channels, vendor key compromise. Each item is copied or recorded as `not stated`.

Open, for the owner:

- Q5. Whether AMD SEV-SNP and other TEEs follow in this RFC or get their own.
- Q6. Where attested rows first appear: a Level 2 file, or an informational annex to Level 1 releases that leaves `levels/L1.yaml` and its digest untouched.
- Q7. Whether the benchmark runs its own `ref-attested` row (vLLM in a TD) on rungs no publisher system covers, in the spirit of `ref-serve`.
- Q8. How tier `reproduced` applies when collateral has moved on: same stored collateral, or fresh collateral on the same evidence.

## References

- [docs/PRD.md](../docs/PRD.md) §5, §10 (v0.3: "TEE attestation baselines").
- [RFC-0018](0018-level-1-ladder.md) SI-4, SI-4a, SI-4b, §Cost, GL-1, GL-2.
- [RFC-0015](0015-reference-rows.md), [RFC-0005](0005-adapter-contract.md) INV-ADAPTER-4, INV-ADAPTER-5, [RFC-0006](0006-reference-hardware-and-cost.md) Q4, [RFC-0008](0008-negative-controls.md).
- `web/_data/facts.json`: Private ML SDK and Tinfoil entries under `another kind of check`.
- [`systems/deepprove/README.md`](../systems/deepprove/README.md) §Weights binding (the verifier-key-from-proof problem Alternative 5 avoids).
- Intel, *Intel Trust Domain Extensions (TDX) DCAP Quote Generation and Verification*, `intel/SGXDataCenterAttestationPrimitives`.
- NVIDIA, *Confidential Computing on Hopper GPUs* and the `NVIDIA/nvtrust` attestation SDK.
- IETF RFC 9334, *Remote ATtestation procedureS (RATS) Architecture*.
