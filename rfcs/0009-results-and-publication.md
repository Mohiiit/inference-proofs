# RFC-0009: Results format and publication

- Authors: AbdelStark
- Created: 2026-11-03
- Requires: RFC-0002, RFC-0003, RFC-0004, RFC-0007, RFC-0008, RFC-0012, RFC-0014, RFC-0015, RFC-0016

## Summary

This RFC defines how benchmark runs are archived on disk, how corrections are issued without rewriting history, how releases are frozen, what the generated static site displays and in what order, how relying parties publish and evaluate performance targets, and what every release report must include. The `results/` directory is strictly append-only. Each release is a frozen, deterministic index compiled from an explicit list of runs. The site is static HTML that works completely without JavaScript, presents each system's claim before any performance number, attaches scope, grade, and tier labels to every figure, and avoids ranking systems.

## Motivation

Published results are the primary artifact readers interact with, and PRD §11 flags out-of-context headline comparisons as the project's chief risk. PRD goals G1 (claim first), G3 (reproducible), and G5 (impartial presentation) translate directly into publication rules here. The initial draft of this RFC established the directory layout, run ID format, and basic concepts of targets and reports, but left unspecified what a release index contains, how multiple repetitions collapse into one published row, how targets are evaluated, and how corrections are recorded without mutating past data.

Concrete scenarios:

- A runner discovers an incorrect CPU binding in an already published run. The original run must remain intact and visible, while the replacement run explicitly documents what it supersedes.
- A policy analyst publishes a target requiring "verification under 60 s on the verifier profile". If a system averages 58 s across repetitions but has one repetition at 63 s, the site must not mark it as meeting the target without exposing that 63 s run.

## Goals

- Keep every run directory self-describing and schema-valid (RFC-0012).
- Never modify or delete files under `results/` after merge; record all corrections as new runs.
- Make `iproofs release freeze` deterministic so identical inputs yield a byte-identical `index.json`.
- Pair every published number on the site with its unit, scope, grade, tier, and a link to its underlying source record (§Site S2 specifies label placement).
- Keep the site free of aggregate scores and arbitrary performance rankings.
- Attribute every target to its author and evaluate compliance conservatively.

## Non-Goals

- Defining metric formulas (RFC-0004), evidence tiers (RFC-0007), negative controls (RFC-0008), or claim card fields (RFC-0002).
- Specifying site hosting or custom domain configuration (Q3).
- Building a separate custom API feed for third-party comparison maps (Q2).
- Building a heavy interactive web application; the site is static HTML readable in full without JavaScript, using client-side script only to sort, search, or disclose content already present on the page (§Site S10).

## Proposed Design

### Storage

```
results/<release>/<system>/<run-id>/
  run.json          every recorded and derived number of this job, each a quantity (RFC-0012)
  manifest.json     everything needed to rerun (RFC-0014)
  controls.json     control outcomes for this job (RFC-0008), or absent if the job ran no controls
  verifier/<proof_id>.json   per proof: verdict, raw exit code, raw last line, verify seconds
  logs/harness.jsonl         structured harness log (docs/spec/05-observability.md)
  logs/<step>.stdout, logs/<step>.stderr   adapter output per step, redacted
  digests.txt       "<name>\t<sha256:...>" per line, sorted: every proof digest, and the digest of every log before truncation
```

`run-id` follows `<YYYY-MM-DD>-<system>-<workload>-<profile>-<n>` as defined in [RFC-0012 §Identifiers](0012-schemas-and-serialization.md#identifiers), using the job's UTC start date.

Top-level structure of `run.json` (`run/1`):

```json
{
  "schema": "run/1",
  "run_id": "...", "release": "v0.1", "system": "sash", "workload": {"id": "...", "version": 1},
  "profile": "prover-h100", "repetition": 1, "control": false, "system_kind": "prover",
  "claim": {"system": "sash", "configuration": "default", "card_version": 1},
  "status": "completed",
  "failure": null,
  "replaces": null,
  "raw": {"setup": {}, "commit": {}, "prove": {}, "verify": {}},
  "adapter_phases": {},
  "metrics": {},
  "events": [{"event": "prove.start", "mono_ns": 0}, {"event": "proof.released", "mono_ns": 0}],
  "proofs": [{"proof_id": "...", "release_mono_ns": 0, "tokens_covered": 0, "verdict": "accept"}],
  "warnings": []
}
```

- `status` is `completed` or `failed`. When `failed`, `failure` holds the RFC-0010 failure record `{kind, step, message, exit_code, last_lines[], at}`; otherwise it is `null`.
- `system_kind` mirrors `kind` from `system.yaml`: `prover`, `reference` ([RFC-0015](0015-reference-rows.md)), or `test` (the fake CI systems). Reference systems skip `commit` and `verify` (recompute jobs time their execution inside `prove`), so their `raw` object omits `commit` and `verify`. Runs with `system_kind: test` never enter a release.
- `events` stores the ordered lifecycle timestamps `{event, mono_ns}` used to derive all timing scopes ([RFC-0010](0010-harness-runner.md), [RFC-0011](0011-measurement-and-sampling.md)); `mono_ns` integers are allowlisted under G5 as structural timestamps, while all published durations are derived quantities.
- `claim` identifies the active claim card by system, configuration, and `card_version`.
- `raw` contains measured step-level quantities, `metrics` contains recorded and derived quantities keyed by RFC-0004 metric IDs, and `adapter_phases` contains adapter-reported phase timings by step (`adapter_phases.<step>.<name>`, `source.kind: adapter`, RFC-0004).
- `replaces` is either `null` or `{run_id, reason}` (§Append-only rule and corrections).
- `inputs` (included on runs recorded from the 2026-11-08 amendments onward) stores runtime copies of the workload's asserted inputs, `active_parameters_per_token` and `weight_bits` ([RFC-0003 WB-4](0003-workloads.md#weight-bits)), referenced directly by derived quantities that depend on them.

Directory size caps:

- Raw proof bytes are never committed; proofs are tracked strictly by digest ([RFC-0014 §Proof digests](0014-provenance-and-integrity.md#proof-digests)).
- Each individual log file is capped at 1 MiB, preserving the first 256 KiB and final 768 KiB separated by `[iproofs: <k> bytes omitted, full digest in digests.txt]`. The full untruncated digest is recorded in `digests.txt` prior to truncation.
- Each run directory is capped at 10 MiB overall. If per-file caps still exceed 10 MiB, adapter logs are trimmed further to their first 64 KiB and final 192 KiB, largest files first, until the directory fits; `harness.jsonl` is truncated last.
- The harness enforces both caps when writing run directories, and CI gate G2 rejects any run directory exceeding them.

### Append-only rule and corrections

1. Once a run directory is merged to the default branch, its files are never edited or deleted. CI gate G2 enforces this by rejecting any pull request diff that modifies or removes an existing path under `results/`.
2. Corrections are submitted as fresh runs with `replaces: {run_id, reason}` in `run.json`, where `reason` explains the issue in one or two sentences. The superseded run remains in `results/` and is labelled as superseded on the site alongside the reason and a link to its replacement.
3. If a run is invalidated by an issue that cannot be fixed merely by rerunning (such as a harness measurement bug), it is replaced by a run from the fixed harness, or, if no rerun is feasible, listed under `superseded_runs` with a reason in the next `release.yaml`. The original record is never deleted.
4. Results recorded under an older RFC version keep their original labels, and every release specifies the exact RFC commit under which it was frozen.

### Configurations and repetitions

A configuration is uniquely defined by `(system, workload id, workload version, profile, adapter image digest, control: false)`. Successive runs of the same configuration carry `repetition` values `1`, `2`, `3`, and so on. Each release publishes one aggregated row per configuration:

- Each metric is published as a summary statistic (RFC-0012) over completed repetitions: `stats.n` (completed count), `stats.n_failed` (failed count), mean, sample standard deviation, minimum, and maximum. Every statistic carries `grade: derived`, `source.ref: derive:D-STAT@<harness version>`, `source.inputs` pointing to each repetition's value in repetition order, and the lowest tier among its inputs (`reported` during the research phase, per RFC-0012 INV-QTY-6a).
- RFC-0004 specifies a minimum of three repetitions. Configurations with fewer than three completed repetitions are still published, tagged `insufficient_repetitions: true` in `index.json` and labelled `"below minimum repetitions"` on the site (RFC-0004 §Statistics) so no data is hidden or overstated.
- Failed repetitions appear alongside their configuration with their failure kind, failing step, and a link to the failed run record.

### Release record

`releases/<release>/release.yaml` (`release/1`), authored in a pull request:

```yaml
schema: release/1
release: v0.1
reference_file: reference/v0.1.yaml
rfc_commit: "<40-hex commit of this repository whose rfcs/ tree is in force>"
harness_version: "0.1.0"
runs:
  - results/v0.1/sash/2026-12-02-sash-sash-l31-8b-c4096-prover-h100-1
  # every run directory included, listed explicitly
superseded_runs: []           # [{run_id, reason}] for runs withdrawn without a replacement run
claim_cards:
  - {system: sash, configuration: default, card_version: 1, path: systems/sash/claims/default.yaml, digest: "sha256:..."}
```

`releases/<release>/index.json` (`release-index/1`), generated deterministically by `iproofs release freeze`, contains:

- `configurations[]`: for each configuration, its constituent runs, per-metric summary statistics, `insufficient_repetitions`, and eligibility status with reasons (RFC-0014 §Eligibility). Every quantity retains the tier recorded in its runs (`reported`).
- `controls[]`: per configuration, tallied counts for every outcome (`rejected`, `accepted`, `no_verdict`, `invalid_call`, `void`, `not_applicable`, `error`, `prover_failed`) plus the full list of controls whose outcomes fell outside their expected sets.
- `targets[]`: all applicable target evaluations (§Targets).
- `claim_cards[]` and `reference` digests as frozen.
- `inputs_digest`: SHA-256 over the sorted digests of every input file read during freeze, enabling anyone to verify identical freeze inputs.
- `freeze_derived` (included only when non-empty): repetition-level derived values computed at freeze time for legacy runs stored before those formulas existed ([RFC-0004](0004-metrics-timing-grades.md#decisions) Q3: D-TPP, D-SPAB-S, etc.), referenced by configuration statistics so `run.json` stays untouched (APP-1).

Every numeric figure inside `index.json` is serialized as a labelled quantity or statistic.

### Freeze algorithm

`iproofs release freeze RELEASE` executes the following steps sequentially, aborting at the first failure with exit code 1 and an error message identifying the offending run and rule:

1. Load and validate `release.yaml`, the reference hardware file, every listed run directory, and every claim card at its pinned digest.
2. Run validation gates G2 through G7 ([RFC-0013](0013-validation-and-ci.md)) across all listed runs.
3. Evaluate eligibility for every run (RFC-0014); ineligible runs are excluded from statistics and recorded alongside their disqualification reasons.
4. Group runs into configurations and aggregate per-metric statistics across completed repetitions in repetition order. For any closed workload, verify that completed runs exist from at least two distinct proving systems matching the workload's exact `claim_class` and that no prover configuration on that workload has a different class (RFC-0003 §Choosing common workloads, Q7 default); otherwise abort the freeze.
5. Aggregate negative-control summaries per configuration.
6. Evaluate all applicable targets (§Targets).
7. Emit `index.json` using the canonical RFC-0012 writer with no wall-clock timestamps, guaranteeing deterministic output.

The freeze pull request commits `index.json`. Once merged, release data is immutable: updates require cutting a new release (such as `v0.1` to `v0.2`), with no in-place point updates.

### Site

`iproofs site build [--out DIR]` compiles the static site into `web/` (committed to git and deployed by Vercel) from the latest frozen `releases/*/index.json` and `release.yaml`, their referenced claim cards and runs, `systems/`, `workloads/`, `reference/`, `targets/`, the criteria file, and `web/_data/facts.json`. `iproofs.site` computes every display value into a single structured view model and passes it to `web/build.py`, which renders the HTML templates without ever hardcoding a number. Passing `--out DIR` writes the complete site to an alternate directory. Every page is complete static HTML readable without JavaScript (S10 bounds what optional script may do), and deployed pages include `noindex`.

The site validates claims against negative controls rather than auditing cryptographic proofs. On any system row, each glyph state reflects RFC-0016: documented by the system at its pinned commit for the exact configuration tested (including its verifier) and not contradicted by the shared negative controls of RFC-0008 (C1 to C8, P1, P2) under RFC-0016's control-override rules (#318). "Not contradicted" applies strictly to controls that executed and produced a verdict: `void`, `not_applicable`, and `error` controls "neither pass nor fail" (RFC-0008 §Outcomes), unexecuted controls test nothing, and system pages list both beside the relevant property (S1). System-specific controls (RFC-0008 §System-specific controls) appear on the system page alongside their expected sets and affect glyph states only where RFC-0016 specifies. Reference row states come from RFC-0015, while unbenchmarked public-source rows reflect public documentation quotes untested by any harness run or control (RFC-0016 §Sources by row class). No page implies an audit, assigns a probability of soundness (RFC-0016 INV-GLYPH-2: properties carry no numeric scores), or asserts a benchmark-assigned security level (RFC-0016 INV-GLYPH-3).

Required site pages (matching `web/` in `web/README.md`, plus remaining v0.1 requirements):

| Page | Content, in this order | Live site, 2026-11-07 |
|---|---|---|
| Overview (`/`) | Legend displaying the six key glyphs with each property's name and question (RFC-0016), the four state names, and a link to `/criteria`; followed by one cross-model table containing one row per benchmarked system (S6), where each row header appears first with the glyph, system name, and pin linking to its validated claims on the system page without inline claim text (S1), followed by model info and metrics; followed by "Not benchmarked yet" listing unbenchmarked systems (RFC-0016 public-source rows) alphabetically with glyph, name, models, and status, and no performance numbers (facts only, S2) | yes, with gaps (below) |
| System (`/<system>`) | System name; for each claim card referenced by the system's rows, in S1 order: validated claims (glyph, and for each property its name, state word, reason, deciding quote with pinned source link or `sources_read` for Not stated, both quotes on conflicts, and every RFC-0016 control outcome tied to that property regardless of outcome); card identity linking to the card file and digest; system facts (kind, model, pinned repos, licence, status, adapter notes; S2); full claim card (RFC-0002) collapsed in a `<details>` block; expanded `quality_gap` and `residual` fields alongside the recompute agreement-rate plate (RFC-0015 RC-5, RC-6; S2, S3); per configuration: heading naming workload, division, and profile, runs excluded from statistics (S7), one metric plate per headline figure (`id="fig-<column>"`; S2, S3), and remaining metrics in a table; full negative-control outcomes per configuration with unexpected outcomes expanded in full (RFC-0008); reference rows for the same workload (RFC-0015) linking to their plates on `/reference` | yes, with gaps (below) |
| References (`/reference`) | Dedicated reference rows rather than system pages (RFC-0015 §Reference systems): for each reference system, its name, glyph (per RFC-0015 and RFC-0016 §Sources by row class), and facts; then per workload, its reference rows under a heading naming workload, division, and profile, with one plate per figure (`id="<reference>-fig-<column>"`) and remaining figures in a table. Carries no claim card or controls, and refers to results as outputs rather than proofs (RFC-0015 REF-2) | yes, with gaps (below) |
| Criteria (`/criteria`) | Opening explanation of what the benchmark measures and does not measure; then for each property, its name, question, definitions of all four states, and scope exclusions per RFC-0016 | yes, without the opening statement |
| Release | Release scope, RFC commit linking to every RFC at that commit, reference hardware file, list of included systems, list of failures, and links to all unexpected control outcomes | yes (`/release`), with gaps (below) |
| Targets | Every published target with its author and evaluated rows showing both mean and least-favourable repetition values (§Targets) | yes (`/targets`, when targets exist); none exist yet |
| Not found | Standard header and "Not found" message, served with HTTP 404 and no numbers | yes |

Every page in the table above is required for v0.1 (with `/targets` generated only when the release evaluates at least one target). Every page footer identifies the release and links to the release page, the release's `index.json` (S5), and `/criteria`.

Pages from the initial draft that v0.1 consolidated elsewhere:

- Home: replaced by Overview at `/`; release links appear in every footer, and benchmark scope opens `/criteria`.
- Workload: the Overview's Model cell names the model, size, and workload shape; system pages show workload ID, division, and profile and link directly to the workload file containing model and prompt digests (RFC-0003); `/reference` holds reference rows.
- Division table: the Overview's single table labels closed and open rows in their Model cell (S6). Each row header now shows the glyph derived from the claim card rather than four raw card fields, while full card text and quotes live on the system page (S1). Closed workload `l31-8b-c1024` publishes once two systems matching its class run it (RFC-0003 §Divisions, Q7, enforced at freeze).
- Controls: moved to system pages (both beside each linked property in validated claims per S1 and in full per configuration after the figures), with `/release` linking every unexpected outcome.
- Methodology: placed on `/release` beside the pinned RFC commit.

Site rules:

- **S1 Claim first.** Every page displaying a quantity or statistic (S2) for a system MUST present the claim card for that number's configuration before any number (RFC-0002 INV-CLAIM-1), following the layout below (see the justification under "How a table across systems meets" below). The system's six-triangle hexagonal glyph summarises that configuration's validated claims: every state reflects upstream documentation for the exact tested configuration (verifier included) as long as negative controls do not contradict it (§Site, RFC-0016), with full quotes, sources, and control records on the system page.
  - In cross-system tables, each row's header comes first and contains (before any figure) the glyph, system name, and commit pin, linking to `/<system>#claims-<configuration>`. When a table includes multiple rows for one system (one per card, RFC-0016 SRC-1), the row header also includes the card's `configuration`. Apart from card identity (`system`, `upstream.commit`, and `configuration` where needed), the row header includes no other claim card fields (`claim_class`, `relation`, `security`, `zero_knowledge`, `assumptions`, `coverage`, `binding`, `residual`, `quality_gap`, `availability`); the glyph summarises the row, with every state present as text in the HTML (S9).
  - On the system page, immediately after the system name and before any quantity or statistic, render each referenced claim card (RFC-0016 SRC-1) under anchor `claims-<configuration>` in this exact order:
    1. Validated claims: the glyph followed by each property's name, state word, explanatory reason (omitted when a Not stated reason merely repeats the state), deciding quote linked to its pinned source (repository, full commit, file path, and lines; INV-CLAIM-3) or `sources_read` for Not stated, plus the conflicting quote and source whenever `conflict: true` (RFC-0016 ST-2, ST-8), and every control outcome tied to that property by RFC-0016 across every run referenced by the row (control ID, outcome, and record link, covering contradicting outcomes, expected outcomes, non-accepting unexpected outcomes such as `no_verdict` or `invalid_call`, and non-testing outcomes `void`, `not_applicable`, `error` with reason, or `"not run"` so untested states never look tested). RFC-0016 determines which controls map to each property.
    2. Card identity (`system`, `configuration`, `card_version` as frozen in `release.yaml` `claim_cards[]`), linking to `claim_cards[].path` at the commit that merged `index.json` (§Freeze algorithm) alongside `claim_cards[].digest`.
    3. System facts (S2).
    4. Full claim card with every field's source link (INV-CLAIM-3), collapsed inside a native HTML `<details>` element present in the initial HTML and toggleable with one click even without JavaScript (S10).
    5. Expanded `quality_gap` and `residual` fields alongside a dedicated plate for the recompute agreement rate (RFC-0015 RC-5, RC-6), with all labels visible (S2, S3).

    Configuration figures follow below.
  - Collapsing the full card inside `<details>` balances INV-CLAIM-1 with readability: the complete card MUST appear in DOM order before the first figure on the system page (a remote link alone would separate the card from its plates), while leaving all raw fields expanded would push every figure several screens down even though the validated claims above already surface every deciding quote one click away (§Site gaps, S1). Because the agreement rate is a statistic, it remains outside the `<details>` fold alongside `quality_gap` and `residual` (S2, S3, RFC-0015 RC-6).
  - Where RFC-0008 §Reporting asks for per-row control counts and full unexpected `accepted` details "in the row", this section satisfies that on the system page linked from every row header (both beside each property in validated claims and in each configuration's controls block), while `index.json` retains full per-configuration `controls[]` counts (§Release record). Q4 records this interpretation.
  - Each glyph renders RFC-0016's six properties in their four states according to row class (§Sources by row class): claim card for system rows, RFC-0015 for reference rows, and public sources for unbenchmarked rows, with each state's reasoning and source quotes either on the page or one link away.
  - Reference rows carry no claim card (RFC-0015 §Reference systems), sit apart from system rows, and link their glyphs to `/reference`. Unbenchmarked systems display no figures, sit in their own section after References (RFC-0016 SRC-8) explicitly stating their states come from public sources rather than claim cards, and link their glyphs to a system page if one exists.
  - How cross-system tables satisfy "claim before numbers": RFC-0002 specifies that "Every published row resolves to exactly one claim card, shown before any number" (§Goals) and "the card for that number's configuration appears before the number" (§Rules 2, INV-CLAIM-1), while RFC-0003 §Divisions specifies native tables "with the claim cards above them". This section treats the row header as meeting both requirements ("above" interpreted as earlier in reading order): at every viewport width (S11), the header precedes every figure in the row, resolves to the single card in force for that configuration (`run.json` `claim`), renders the validated glyph states derived from that card and its negative controls (RFC-0016 SRC-1) as text in the HTML, and links directly to the quotes, sources, controls, and full card on the system page. (The initial version similarly put a four-field summary in the table rather than the full card.) Because no raw claim text sits inline in the overview row, this is a pragmatic reading rather than a literal one; Q4 records it without modifying RFC-0002 or RFC-0003.
  - Responsive layouts at any viewport width must never reorder figures ahead of their row header, nor place a system page's figures ahead of its validated claims and claim card (S11).
- **S2 Labels with every number.** Every displayed quantity and statistic (RFC-0012) carries its unit, timing scope (when non-null), grade, and tier, plus a link to its JSON Pointer in the published record. Descriptive facts about a workload, model, or commit pin (prompt length, batch size, parameter count, dates, commit hashes) are not quantities and simply link to their source records. "One proof covers" (RFC-0004 §Tokens covered) is a quantity and carries its RFC-0004 grade like any other. Label placement:
  - On system and reference pages, all labels are visible directly on each figure's plate or table row.
  - In cross-system tables, the unit stays visible while scope, grade, and tier MAY move into the cell's accessible description, provided the figure links directly to its full plate (`/<system>#fig-<column>`, or `/reference#<reference>-fig-<column>`) where every label and source link are visible. Whenever rows inside one column differ in scope, grade, or tier, each cell keeps its differing label visible.
  - Display labels MAY translate enum strings into plain wording (for instance, `"calculated from recorded numbers"` for grade `derived`) using a single consistent mapping in the generator, while the linked record retains the exact stored enum.

  This preserves AGENTS.md rule 2: every number carries its full labels in the page HTML and shows them visibly on its plate at most one click away, enforced by site golden tests (`docs/spec/07-testing-strategy.md`).
- **S3 Ranges.** Statistics display six values (`mean`, `stdev`, `min`, `max`, `n`, `n_failed`) plus `"below minimum repetitions"` whenever applicable (§Configurations and repetitions). System and reference pages display all six visibly on every plate and table row. Cross-system tables show the mean alongside `n`, `n_failed`, `min`, and `max`, optionally moving `stdev` (and, at viewports `<= 560 px`, `n`, `n_failed`, `min`, and `max`) to the accessible description and linked plate as in S2. `"Below minimum repetitions"` is never hidden.
- **S4 Display rounding.** Numbers display to 4 significant digits using an SI (or binary, for MiB) prefix that keeps the printed value between 1 and 1000 wherever possible (e.g. `68.21 µs` rather than `0.06821 ms`). Rounding affects presentation only (RFC-0012): full precision remains in the linked JSON record (S2), and all column sorting uses an unrounded sort key in one base unit computed programmatically by the generator (AGENTS.md rule 3). A `title` attribute MAY repeat the full value, but does not satisfy this rule on its own.
- **S5 No ranking.** In the initial HTML, overview rows appear ordered ascending by each row's headline overhead against production serving (RFC-0004 INV-DERIVE-10, -11), with rows lacking an overhead placed last, breaking ties by system name, then profile ID, then position in `index.json`; this same default order applies whenever the URL carries no hash. With JavaScript enabled, readers MAY click column headers (`System` or any numeric column; `Model` is unsortable) to sort, clicking a second time to reverse direction. The active sort persists in the URL hash as `#sort=<column>-<asc|desc>` so shared links preserve sort order, while removing the hash, navigating Back to a hashless URL, or supplying an unknown sort restores the default order. Rows lacking a value in the sorted column always sort last in both directions, and ties preserve the default order. Without JavaScript, readers still see every row and figure in default order, column headers do not appear clickable, and every footer links `index.json` for custom analysis (Q2). Reference rows and unbenchmarked systems are never mixed into system sorting. Search results rank by match location, entry type, match closeness, and name (placing unbenchmarked systems last), never by performance metrics. Although the default table order uses a measured column, rows carry no rank numbers, medals, aggregate scores, or highlighted extreme values (the sorted column itself MAY be visually distinguished, but no individual row or cell within it is highlighted).
- **S6 Divisions.** The overview presents a single cross-model table with one row per benchmarked system, selecting the configuration named by `overview_workload` in `web/_data/facts.json` (for FlashProve, `fp-maverick-w1024-b24`, matching its published steady batch) or the system's sole configuration; having multiple configurations without `overview_workload` fails the build. Additional configurations appear on the system's own page. Reference rows are excluded from this table because production serving forms the denominator of the overhead column and is named inside each overhead cell. Table columns:
  1. `System`: system header with model details underneath (model name, total and active parameters, weight width, workload shape, plus division label for closed or open workloads per INV-WL-5).
  2. Overhead against production serving: the release's `overhead_headline` (D-OVERHEAD-S, or D-OVERHEAD-WARM where no steady scope exists), showing scope, prover/serving run counts, pairwise range, and proved vs served precision.
  3. Three cost columns sharing a unified normaliser header, per token covered per Gbit of active weights (`active_parameters_per_token × weight_bits`, RFC-0004 INV-DERIVE-7): proving time (D-SPAB-S at `prove.steady`, falling back to `prove.session` if null, in ms with scope), proof size (D-BPAB, in kB), and verification time (D-VSPAB, in ms with scope).
  The INV-DERIVE-7 attention caveat and weight width appear in each column's description and linked plates, and each cell displays sample size and range (abbreviated with scope on narrow screens). Every numeric column sorts by stored values (S4, S5), including rows with partial weight widths (such as SASH, with its width noted under the system name; for the overview table this overrides RFC-0004 INV-DERIVE-7's exclusion of `covers: part` rows from sorting). Absolute proof sizes and verification times for each workload remain on the system page, which also displays the division beside each workload.
- **S7 Runs left out of the figures.** Above each configuration's figures on its system page, list all superseded, ineligible, and failed runs with links to their records: superseded runs show their reason and replacement link, ineligible runs list their disqualification reasons, and failed runs display failure kind, step, exit code, and last log line, alongside the count of completed runs feeding the statistics. Excluded runs never enter statistics, and their status is written in words rather than indicated solely by strikethrough (S9). Cross-system tables show `n_failed` (S3) and link every figure to its plate directly below this list, giving one-click access to failed runs (serving as this section's reading of §Configurations and repetitions' "listed in the row").
- **S8 Neutral text.** All site prose MUST pass CI gate G8 (RFC-0013).
- **S9 Accessibility.** Tables preserve full semantic structure via native `<table>` elements with `scope` attributes, or explicit ARIA `table`, `row`, `columnheader`, `rowheader`, and `cell` roles when responsive layouts reflow rows into blocks. Every cell maps to one column header and one row header, and sorted column headers carry `aria-sort`. Information is never conveyed by colour alone: every glyph state appears as text in the HTML (inside row headers right after the system name so the header's accessible name stays clean, and visibly on system pages), reveals as text on hover, tap, and keyboard focus, and maps to named legend colours with an achromatic ink for Not stated. Pages SHOULD pass automated WCAG 2.2 AA audits at desktop and mobile widths.
- **S10 Script.** Every page works completely without JavaScript; optional script acts strictly as progressive enhancement:
  - All rows, figures, labels, glyph states, and links exist in the initial server-rendered HTML in default order (S5).
  - Script MAY only reorder table rows (S5), perform local search over build-generated `search.json` (whose entries all point to pages on the site), or reveal existing page content (glyph state tooltips on hover/tap, mobile search drawer). It never inserts, removes, or alters any number, label, or glyph state, and search displays only `search.json` matches plus the count of unlisted matches.
  - Script-only controls stay hidden or visually inert when JavaScript is disabled.
  - All assets (scripts, stylesheets, fonts, images, frames) are self-hosted on the site origin; inline scripts are allowed only when matched by hash in Content-Security-Policy. External hyperlinks are permitted, but pages make zero third-party requests, include no analytics, execute search locally in the browser, and store nothing in cookies or web storage (persisting state solely in the URL hash).
  - Untrusted submission data never executes as code; all data is HTML-escaped text (`docs/spec/06-security.md` §Trust boundaries, item 5).
  - Row reordering animates instantaneously under `prefers-reduced-motion`.
- **S11 Narrow screens.** All pages render cleanly down to 320 CSS px with zero horizontal scrolling, reflowing wide tables instead of scrolling sideways. Every S2 and S3 label stays accessible on touch devices (either visible or in accessible text and visible on the linked plate; `title` alone is insufficient on touchscreens). Interactive links and buttons have touch targets at least 24 CSS px tall without overlapping, and S1's claim-first DOM order holds across all widths.

Summary of 2026-11-07 revisions aligning this section with the published `web/` site:

| Rule | Kept or changed | Reason |
|---|---|---|
| Page table | Changed to the live page set plus Release and Targets; folded Home, Workload, Division table, Controls, and Methodology into other pages and added `/reference` | Overview at `/` delivers the tables readers seek directly; `/reference` hosts canonical reference plates once while system pages retain reference links and agreement rates (RFC-0015) |
| Script sentence and §Non-Goals | Changed to S10 | Local sorting and search improve usability without altering page data; full no-JS reading and zero external asset loading remain intact |
| S1 | Changed to put the card-derived glyph (with name, pin, and optional configuration) in cross-system row headers with no inline claim text, moving full validated claims, control outcomes, card identity/digest, collapsed full card, and open `quality_gap`/`residual`/agreement-rate to the system page; interpreted "in the row" wordings in RFC-0002 and RFC-0008 via the system page | Reflects the claim-validation model (§Site): glyphs compare six properties compactly across systems while quotes, sources, and controls live on system pages; INV-CLAIM-1 remains intact as recorded in Q4 |
| S2 | Changed to permit hiding scope, grade, and tier in cross-system tables (keeping them in accessible descriptions and linked plates), allow plain display wording, and classify "One proof covers" as a quantity | Keeps multi-column tables readable while preserving all labels in HTML, on plates, and visibly wherever rows in a column differ |
| S3 | Changed to allow hiding `stdev` in cross-system tables, and `n`, `n_failed`, and range below 561 px | Same rationale as S2; system and reference pages always display all six statistics |
| S4 | Changed so full values live in linked JSON records and sort keys, making `title` optional | `title` attributes are inaccessible on touch and keyboard devices; linked records serve both readers and automated checks |
| S5 | Changed to header-triggered sorting persisted in the URL hash, keeping all ranking bans | Maintains one URL per page, preserves Back-button behaviour, and keeps initial HTML in deterministic order (§Alternatives Considered) |
| S6 | Changed to per-model/workload tables naming divisions, with card-derived glyphs in each row header | Preserved separate native workload tables per RFC-0003 §Divisions with headings satisfying INV-WL-5 (later superseded by the 2026-11-09 cross-model table amendment below) |
| S7 | Changed to label excluded runs explicitly in words with links above figures | Strikethrough alone fails S9 accessibility and harms readability; failed runs join the same list reachable in one click from overview plates |
| S8 | Kept | |
| S9 | Changed to allow ARIA table roles alongside native `th`/`scope` and require text glyph states | Reflowing tables into stacked cards on mobile can break native table semantics in some browsers; explicit ARIA roles preserve accessibility |
| S10 | Added | Replaces the earlier script ban with progressive enhancement rules |
| S11 | Added | Ensures shared links opened on mobile preserve labels, touch targets, and claim-first ordering |

Summary of 2026-11-08 revisions (#333, per the owner's decision to `"drop the all systems table, no repetition please"`):

| Rule | Kept or changed | Reason |
|---|---|---|
| Page table | Changed Overview to order per-model tables by total parameters with no cross-model summary table | Eliminated printing every system row twice (§Alternatives Considered) |
| S5 | Changed default ordering to follow S6's table sequence with alphabetical rows per table, sorting within each table only | Adapted default ordering to per-model tables |
| S6 | Defined model size as `workload.model.parameters.total` (ties by model name), placed every row in exactly one table, kept closed/open workloads in dedicated tables (Q5), and deferred any cross-model table until a sortable cross-model metric existed (RFC-0004 INV-DERIVE-7) | Avoided repeating rows before cross-model sorting was available (subsequently superseded on 2026-11-09 when the unified cross-model table landed) |

Known gaps between the live `web/` implementation and these rules:

- S1: glyph states currently load from `web/_data/criteria.json`; system pages print property name, state, reason, a "source" link to `#read-<property>`, and override controls beside each property, while deciding/conflict quotes, `sources_read`, and control outcomes live collapsed inside "How we read it" (`<details>`) after the glyph and before card identity rather than inline beside each property; supporting, `aside`, and `outside_pin` quotes plus cell `note` fields (RFC-0016 OVR-7) are omitted; rows are keyed per system (one card row per system); card file links point to `main` rather than the `index.json` merge commit; "Not benchmarked yet" omits the public-sources disclaimer, reasons, and quotes (per an owner layout choice) and includes some web quotes disallowed by RFC-0016 SRC-9 (see RFC-0016 §Migration / Rollout).
- S2: plates, overview cells, and secondary tables currently show `index.json` JSON Pointers as plain text rather than clickable links, and model facts do not yet link to model records.
- S4: until S2's record links are wired up, full stored values exist only inside hidden overview sort keys.
- S6: the Overview's Model cell displays model name and shape without the workload ID, profile, or workload link (per an owner layout choice); all three appear on the system page.
- S9: glyph state text does not yet appear on keyboard focus.
- Pages: `/criteria` currently omits its opening scope paragraph; system pages do not embed reference rows inline (they live on `/reference`); single-configuration system pages title their figures section with model and shape rather than workload/division/profile (division appears under Tamper tests); `/release` links to the `rfcs/` directory at the RFC commit rather than individual RFC files; `/reference` lacks per-workload headings and secondary metric tables, and titles each reference glyph `"What one proof establishes"` (contrary to RFC-0015 REF-2).

### Targets

Relying parties submit performance or verification targets at `targets/<author>/<id>.yaml` (`target/1`):

```yaml
schema: target/1
id: verify-under-60s
author: {name: "<person or organisation>", affiliation: "<organisation>"}
date: "2027-01-10"
metric: verify_seconds            # an RFC-0004 metric id
comparator: "<="                  # one of <=, >=, ==
threshold:
  value: 60
  unit: s
  scope: verify
  grade: asserted
  tier: reported
  source: {kind: reference_file, ref: "targets/<author>/verify-under-60s.yaml#/threshold"}
  null_reason: null
claim_class: "*/exact-match/*"     # RFC-0002 claim-class pattern, `*` matches one segment
applies_to:                       # optional extra filter; every listed key must match the claim card
  coverage.phase: prefill
  zero_knowledge.claimed: true
profile: verifier-cpu             # optional; restricts to rows on this profile
rationale: "One or two paragraphs in the author's words."
```

Evaluation rules for each configuration in a release whenever a target's `claim_class` pattern matches the card's `claim_class` (RFC-0002), every `applies_to` predicate matches the card, and `profile` (if specified) matches:

1. If the configuration's metric is missing, null, or differs in unit or timing scope from `threshold`, record `not_evaluable` along with the reason.
2. Otherwise evaluate against the least favourable completed repetition: maximum for `<=`, minimum for `>=`, and every repetition for `==`, producing `meets` or `does_not_meet`.
3. Targets whose `applies_to` filter does not match are omitted for that configuration.

Evaluating against the worst completed repetition rather than the mean is intentional: a target represents a practical bound a relying party depends on, and a configuration whose mean passes while an individual repetition breaches the limit does not reliably meet it. The site displays both the mean and the least-favourable value next to each verdict. The benchmark project never publishes targets of its own (PRD §9). Targets are attributed, versioned in git history, and frozen into each release's `index.json` so later target edits never retroactively change past releases.

### Reports

Each release ships one written report at `reports/<release>.md` with three required sections in order: what changed since the prior release, what failed (failed runs and unexpected negative-control outcomes), and what the numbers do not show (covering every open `RISK` across the RFCs). Every figure cited in a report is copied verbatim from `index.json` with its unit, scope, grade, tier, and row link. Reports never introduce ad hoc calculations (AGENTS.md rule 3); any new ratio must land in `iproofs.derive` first.

### Failure modes

| Failure | Response |
|---|---|
| Pull request edits or deletes an existing file under `results/` | Gate G2 rejects it under append-only rule `APP-1` |
| Run directory exceeds 10 MiB | Harness truncates logs at write time; G2 rejects any directory still over the cap |
| Configuration has fewer than 3 completed repetitions | Published with `insufficient_repetitions: true` and visible label |
| Listed run fails eligibility checks | Excluded from summary statistics and displayed with disqualification reasons |
| Target references an unknown metric ID | Gate G2 fails with `XREF-5` |

## Alternatives Considered

**Allowing in-place result edits and relying on git history as an audit trail.** Simpler to manage, but rejected because site readers do not inspect git diffs and corrections must be visibly transparent on the site itself. Append-only storage with explicit `replaces` links makes corrections first-class data.

**Publishing a single chosen repetition or only the median.** Rejected under AGENTS.md rule 5 and PRD N3: mean, full range, and sample size `n` are reported together, whereas the median adds little clarity at `n = 3`.

**Evaluating targets against the configuration mean.** Aligns with headline numbers, but rejected for the worst-case reliability rationale in §Targets; the mean appears beside the verdict instead.

**Defaulting to a single sort by cost per proved token.** Familiar to readers, but rejected because a cost-based default sort acts as an implicit ranking (PRD §5) and native workloads are not directly comparable.

**Showing an all-systems cross-model table above per-model tables.** Proposed in #333 (displaying every system with overhead and D-SPAB-S sorted by model size above per-model tables of absolute metrics) so readers could scan all systems at once. Rejected by the owner on 2026-11-08 because it duplicated every system row and glyph while nominal weight widths kept D-SPAB-S unsortable (RFC-0004 INV-DERIVE-7) and overhead already appeared in each per-model table. (Ordering per-model tables by `parameters.total` is not a performance ranking because model size is fixed by the workload rather than by prover results.) A single cross-model table returned on 2026-11-09 without duplicating per-model tables.

**Generating separate static HTML pages for every sort column and direction to avoid JavaScript.** Used in the original S5 design prior to #320 so sorting worked with zero script. Rejected on 2026-11-07 because duplicating all data across `2 × columns` pages multiplied golden files and link checks, trapped shared links in non-default orders without an easy reset, and added no value for no-JS readers who already get the default order in HTML plus `index.json` in the footer. Hash-based client-side sorting (S5) keeps one canonical URL per page while preserving shared sort states and clean Back navigation.

**Using strikethrough styling for superseded and ineligible runs.** Used in the original S7 design, but rejected on 2026-11-07 because visual strikethrough conveys status by styling alone (failing S9) and reduces readability; explicit text status labels replace it (S7).

**Running a dynamic database-backed web app.** Rejected for v0.1 because static HTML is trivial to host, archive permanently per release, and mirror without anyone having to operate a server impartially.

## Drawbacks

- Append-only result directories cause repository storage to grow monotonically (bounded by the 10 MiB cap per run directory, motivating strict log truncation).
- Worst-repetition target evaluation penalises high-variance systems relative to their mean, which is intentional and disclosed on the Targets page.

## Migration / Rollout

Implementation proceeds in stages: run directory writer with fake CI systems, initial real prover runs, release freeze, static site generation, and release reports. The original directory layout stays intact, extended with `replaces`, `releases/`, size caps, and the freeze pipeline.

Amendment of 2026-11-09 (RFC-0015 SRV-6 production serving): updates display rules so the overhead column reports overhead against production serving (`overhead_vs_production_prove.steady`, worded explicitly around production serving), rendering the auto-generated RFC-0004 INV-DERIVE-9 conditions line and precision note from `overhead_conditions`. SASH rows state why no steady figure exists. S6 remained single-model at that step.

Amendment of 2026-11-09 (RFC-0004 INV-DERIVE-11): when a system lacks a steady scope (SASH), the overhead column displays D-OVERHEAD-WARM (`overhead_vs_production_warm`) per `overhead_headline`, comparing proving session against warm steady serving. Under S2, both scopes appear explicitly: cells print `"proving session (start-up included; it proves one request at a time) vs warm serving (steady)"` beneath the value, plates show the same scope line with warm conditions, precision note, and the reason steady is null, and no high-load figure appears alongside it (RFC-0004 Q6). Warm figures are never labelled as steady or as dual-session. Under S5 and S6, warm and steady figures sort together only within a shared workload table while keeping each cell's scope label (RFC-0004 Q5).

Amendment of 2026-11-09 (the cross-model table): updates S5 and S6 as written above, removing per-model tables, the native banner, and the References table from `/` in favour of one cross-model table (one row per benchmarked system, default-sorted ascending by overhead against production serving) and adding optional `overview_workload` to `site-facts/1`. A follow-up amendment on the same day moves model info beneath the system name and replaces absolute proof size and check time on `/` with the three unified per-token-per-Gbit-of-active-weights columns (D-SPAB-S, D-BPAB, D-VSPAB), keeping absolute workload figures on system pages.

Amendment of 2026-11-09 (overview cells): trims text beneath each overview figure down to a single short scope label where rows in a column differ (`"steady"`, `"session"`, `"session vs warm"`), moving full scope text, run counts, range, precision note, grade, tier, and record details into the cell's accessible `title` (per S2) and visibly onto the linked plate (adding prover/serving run counts and range to overhead plates). This supersedes the verbose overview cell text of the two amendments above while leaving plate wording intact.

Amendment of 2026-11-09 (site review): incorporates an owner-approved design review that overrides earlier details where they differ:

- Page table, Overview, and S9: the legend shows only the six property names and questions; state words appear in each slice tooltip (hover/tap), in row header text, and on `/criteria` (linked in every page header). Not stated cells render and read as No, with their reason explaining that upstream did not state the property (RFC-0016 ST-2).
- S1: overview row headers display the glyph and system name, placing the commit pin in the name's title and printing it on the system page.
- S2, S3, S6, and overview cells: each overview cell's title holds value, scope, run counts, range, grade, and tier, while its source record lives on the linked plate (S2). The INV-DERIVE-7 caveat appears once in the shared title of the three per-Gbit headers and in the table's accessible description, weight width sits in the row header, standard deviation lives on each figure's plate, and check time notes its thread count beneath its value.
- S2, S3 on system pages: each configuration opens with a human-readable setup heading (raw IDs in its title) followed once by shared labels (workload, division, profile, grade, tier, index record prefix) and its runs line (`n` and `n_failed`). Each metric plate displays the mean (noted in its title), spread (`min` to `max` using only the significant digits needed to distinguish bounds, plus `sd`, or stating constant across runs), scope (for timed metrics), and record key (amendment of 2026-11-09, research phase). The per-Gbit basis (weight width, note, INV-DERIVE-7 caveat) appears once beneath the three per-Gbit plates, and full overhead conditions, precision note, and high-load context (RFC-0004 INV-DERIVE-9) span full width beneath the plates, leaving the overhead plate with value, pairs, scope, and record key.
- S1 item 5: when a claim card states neither `quality_gap` nor `residual` and no agreement rate exists for the same reason, render one concise line in place of the plate.
- S5: search groups matches by category (benchmarked systems, references, properties, pages, then unbenchmarked systems), ordering within each group by match field, closeness, and name, with static pages indexed.
- Page table, Reference: any reference whose six glyph states are identical shows its glyph once with a single summary line, followed by production-serving measurements (steady GPU time per token, rate, and cost per 1M tokens) as one row per configuration with scope and `n` beneath each value and full labels/record in its title.
- Page table, Release: groups runs by configuration (and by load point for serving configurations) sorted by date and ordinal; footers name the release and licence; `/release` surfaces `index.json` and the criteria file with its digest.
- RFC-0008 §Reporting: any control accepted solely because it mutated an unread proof part (RFC-0008, amendment of 2026-11-09) is displayed as testing nothing alongside its trials and sibling runs, listed separately from unexpected outcomes on `/release` without modifying stored records.

## Testing Strategy

- `harness/tests/unit/test_results_writer.py::test_log_truncation_keeps_head_and_tail`, `::test_untruncated_digest_recorded`, `::test_run_dir_cap_enforced`.
- `test_append_only.py::test_modified_run_file_rejected`, `::test_deleted_run_rejected` (G2 `APP-1` against a two-commit fixture repository).
- `test_freeze.py::test_deterministic_index` (freezes the fixture release twice from distinct working directories and asserts byte-identical `index.json`), `::test_insufficient_repetitions_flagged`, `::test_ineligible_run_excluded`, `::test_superseded_run_excluded_and_listed`, `::test_closed_workload_needs_two_systems`, `::test_closed_workload_of_one_system_stops_freeze` (RFC-0003 Q7).
- `test_targets.py::test_least_favourable_repetition_used` (repetitions 58 s, 59 s, 63 s against `<= 60 s` yields `does_not_meet`), `::test_scope_mismatch_not_evaluable`, `::test_applies_to_filter_hides_target`.
- Site tests: `harness/tests/golden/test_site_golden.py::test_site_matches_golden` compiles the fixture release site and diffs HTML against `harness/tests/golden/site/`; `harness/tests/unit/test_site.py` parses rendered HTML and enforces:
  - `::test_page_set_and_footer` (page table): verifies all required pages exist, `/targets` renders only when targets are present, and every footer names the release and links to `/release`, `index.json`, and `/criteria`.
  - `::test_every_number_has_labels` (S2): verifies unit, scope, grade, tier, and source links appear visibly on plates/tables, or (in cross-system tables) unit visibly with remaining labels in accessible descriptions and linked plates, plus visible differentiating labels where rows differ.
  - `::test_glyph_before_numbers` (S1): verifies row headers with glyphs precede row figures in DOM order, linking system headers to `/<system>#claims-<configuration>` and reference glyphs to `/reference`.
  - `::test_claim_card_before_numbers` (S1, INV-CLAIM-1): verifies cross-system row headers precede figures and hold glyph state words, name, pin, claims link, optional `configuration`, and no other card fields; on system pages, verifies DOM ordering of validated claims (property states, reasons, pinned deciding/conflict quotes or `sources_read`, and linked RFC-0016 control outcomes including `"not run"`), card identity linking `claim_cards[].path` at the `index.json` merge commit with matching SHA-256 `claim_cards[].digest`, and full `<details>` claim card before all quantities/statistics, followed by open agreement rate with `quality_gap` and `residual`, matching RFC-0016 criteria states.
  - `::test_statistics_shown` (S3): confirms all six statistic fields and `"below minimum repetitions"` (when applicable) appear visibly on system and reference pages.
  - `::test_sort_key_is_stored_value` (S4, extending `::test_display_rounding`): verifies sort keys match stored base-unit values and printed figures round to 4 significant digits with SI/binary prefixes avoiding leading zeros.
  - `::test_default_order_by_overhead` (S5): verifies default HTML row ordering by ascending overhead (nulls last, ties by name) with `aria-sort` on the overhead header.
  - `::test_board_order_by_hand` (S5): checks hand-constructed rows sorting ascending by overhead across scopes (nulls last), breaking ties by case-insensitive system name, profile ID, and `index.json` index.
  - `::test_one_row_per_system` (S6): confirms one cross-model table with one row per benchmarked system on its `overview_workload` (or sole configuration), one glyph per system, and no reference rows.
  - `::test_each_figure_names_its_scope` and `::test_deployed_figures_by_hand` (S2, S6): verifies overview cell titles, single-word scope sub-labels, check-time scope, row-header weight width, and hand-verified deployed values against `index.json` (proving `68.21 µs` and `75.41 ms`, proof size `222.9 B` and `639.9 kB`, check `198.7 µs` and `51.04 ms` per token per Gbit of active weights).
  - `::test_no_ranking` (S5, extending `::test_no_aggregate_score_column`): verifies absence of rank numbers, medals, aggregate scores, or highlighted extremes across all pages.
  - `::test_division_named` (S6): verifies system pages display workload, division, and profile, and closed/open overview rows display their division in the Model cell.
  - `::test_runs_left_out_listed` (S7, replacing `harness/tests/unit/test_site.py::test_superseded_and_ineligible_struck_through`): verifies superseded and failed fixture runs appear above figures with reasons, exit code, last line, and links, stay out of statistics, and sit one click from overview figures.
  - `::test_table_semantics` (S9): confirms every cell resolves to one column header and one row header (`th`/`scope` or ARIA table roles) and every glyph state appears as text in the HTML.
  - `::test_reads_without_script` (S10, replacing `harness/tests/unit/test_site.py::test_no_script_tags_required`): confirms all content exists in static HTML, all scripts are self-hosted or CSP-hashed inline scripts, and zero third-party subresources load.
- Headless browser tests on CPU against the built site served with production HTTP headers (e.g. `harness/tests/browser/test_site_browser.py`, alongside `web/shoot.mjs` which currently exercises most of these checks):
  - `test_script_off` (S10): confirms identical visible text with JavaScript disabled, hides script-only controls, and serves the 404 Not found page (with no numbers) for unknown paths.
  - `test_sort_from_hash` (S5, S10): tests header clicks and `#sort=` hashes across all columns/directions, default fallback and hash cleanup for invalid hashes, Back-button restoration, nulls-last sorting in both directions, text invariance across sorts, no row highlights, and instant transitions under `prefers-reduced-motion`.
  - `test_search_local` (S5, S10): confirms search fetches only local `search.json`, sends no network requests while typing, writes nothing to browser storage, displays only `search.json` matches in documented priority order (unbenchmarked systems last), and stays hidden without script.
  - `test_states_as_text` (S9): confirms glyph states appear as text matching the page HTML on hover, tap, and keyboard focus.
  - `test_narrow_screens` (S11): checks 320, 360, and 390 px widths plus landscape phone across all pages for zero horizontal overflow, reachable S2/S3 labels, non-overlapping >= 24 px touch targets, and claim-first row ordering.
  - `test_accessibility_check` (S9): runs an automated WCAG 2.2 AA audit on every page at desktop and mobile viewports.

## Decisions

- Q1. Proofs are archived strictly by cryptographic digest; storing raw proof archives is not required.
- Q2. Each release's `index.json`, published alongside the static site, serves as the machine-readable feed for external comparison maps.
- Q3. The live site is deployed by Vercel directly from the committed `web/` directory (§Site).
- Q4. Cross-system tables satisfy RFC-0002 INV-CLAIM-1 ("the card for that number's configuration appears before the number") and RFC-0003 §Divisions ("with the claim cards above them") via row headers containing the glyph, system name, and pin without inline card text (S1): each header precedes its row's figures, maps to one exact claim card, reflects validated glyph states from that card and its negative controls (RFC-0016), and links to full quotes and the complete card on the system page. This implements the 2026-11-07 decision that the benchmark validates claims rather than auditing them and uses glyphs rather than raw card paragraphs on the overview. The same practical reading applies to RFC-0008 §Reporting ("per row" control summaries and full unexpected `accepted` outcomes appear on the system page and in `index.json` per configuration rather than inline inside overview row headers).
- Q5. The overview displays one row per benchmarked system (S6); additional configurations (including closed or open workloads) appear on each system's page, and closed workload `l31-8b-c1024` withholds published rows until at least two systems matching its class run it (RFC-0003 Q7).

## References

- PRD §4 goals G1, G3, G5; §7 N2, N3; §9 targets; §11 risks.
- [RFC-0002](0002-claim-card.md), [RFC-0003](0003-workloads.md), [RFC-0004](0004-metrics-timing-grades.md), [RFC-0007](0007-evidence-tiers-and-reproduction.md), [RFC-0008](0008-negative-controls.md), [RFC-0012](0012-schemas-and-serialization.md), [RFC-0013](0013-validation-and-ci.md), [RFC-0014](0014-provenance-and-integrity.md).
- MLPerf submission review practice; Ethproofs per-prover rows (PRD §2).
