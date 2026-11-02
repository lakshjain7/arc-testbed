# Survey paper: outline (draft 1, 2 Nov 2026)

## Working title
**How Is Automated Microservice Remediation Evaluated? A Comparison of Benchmarks, Metrics and Safety Mechanisms**

One-sentence claim to test (not yet a result): *systems and benchmarks for automated remediation of microservices report success of the
repair, but almost none measures what the repair does to the other services.*

## Why this paper, and how it differs from the ARC papers
- The ARC dataset paper (MSR 2027) and the ARC method paper describe our own data and model. This survey describes **other people's
  work** and the way it is evaluated. No text, tables or results are shared between them.
- ARC appears in the survey only as one row, marked as ours, and in the "open gap" discussion. Keep the tone neutral; the survey must
  stand without ARC.
- The survey is a team paper: each author reads and fills in part of the comparison table (see "Work split").

## Research questions
- **RQ1.** What systems, agents and benchmarks for automated remediation (and the diagnosis that feeds it) exist for microservice systems?
- **RQ2.** How is each evaluated: environment (real cluster, simulator, replayed data), fault source, action space, definition of success, metrics?
- **RQ3.** What safety mechanisms limit the harm of a wrong action (sandbox, policy, constraint in the learner, prediction before acting, rollback)?
- **RQ4.** What is not measured today, in particular the damage to services other than the target, and what would be needed to measure it?

## Scope
Include: peer-reviewed or well-documented preprint work from 2019 to November 2026 on (a) automated or LLM-agent remediation of
microservice/cloud incidents, (b) benchmarks, datasets and environments used to evaluate it, (c) diagnosis (root-cause analysis)
benchmarks only where they are reused to evaluate remediation, (d) industrial blast-radius and safe-change systems that are publicly
documented.
Exclude: pure anomaly detection, log parsing, capacity planning, non-cloud systems, papers without enough method description to fill the table.

## Search protocol (to be recorded as we go, so the paper can state it)
- Sources: arXiv, IEEE Xplore, ACM Digital Library, DBLP, Google Scholar; plus backward and forward citation chasing from the seed list.
- Query strings (combine, record the date and the number of hits for each):
  `"microservice" AND ("remediation" OR "auto-remediation" OR "self-healing" OR "mitigation") AND ("benchmark" OR "evaluation")`,
  `"AIOps" AND "agent" AND "benchmark"`, `"blast radius" AND ("microservice" OR "Kubernetes")`,
  `"safe remediation" OR "safe action" AND "cloud"`, `"root cause analysis" AND "benchmark" AND "microservice"`.
- Screening: title and abstract, then full text. Keep a log (identified, screened, excluded with reason, included). Two authors screen the
  same 20% to check agreement.
- Quality note for each included paper: peer-reviewed or preprint, artefact released or not.

## Comparison axes (columns of the main table)
1. Task: diagnosis / remediation / both / safety layer
2. Environment: live cluster, simulator, replayed traces; which application
3. Fault source (injection tool, real incidents, synthetic)
4. Action space (which repairs, how many)
5. Ground truth for "success" (oracle script, human, LLM judge, health check)
6. Metrics (success rate, MTTR, false-remediation rate, accuracy at k, ...)
7. **Collateral damage measured?** none / system-level only / per service
8. Safety mechanism (sandbox, policy gate, constrained learner, prediction, rollback, none)
9. Artefacts released (code, data, environment) and licence
10. Venue and status (peer-reviewed or preprint)

## Seed list (to read; verification status as of 2 Nov)
Status: **V** = existence checked against arXiv by tool; **U** = taken from our earlier notes, not yet re-checked. Nothing is cited until read.

| Group | Work | Status |
|---|---|---|
| Remediation, risk | Dai et al., safe remediation as a risk-constrained decision (arXiv:2607.20005) | V |
| Remediation, safety | Cai et al., GuardedAct, blast-radius-aware sandboxing (arXiv:2609.11264) | V |
| Remediation benchmark | MicroRemed (arXiv:2511.01166) | V |
| Remediation evaluation | Qi et al., recovery-aware evaluation (arXiv:2607.04623) | V |
| Agent environments | AIOpsLab (arXiv:2501.06706) | V |
| Agent environments | SREGym (arXiv:2605.07161) | V |
| RCA benchmark | RCAEval (arXiv:2412.17015) | V |
| RCA benchmark | Fang et al., fault-propagation-aware benchmark (arXiv:2510.04711) | V |
| Remediation | E2E-REME (arXiv:2604.11094) | U (first one to read; notes say it may be close to ARC) |
| Remediation | Rebooting Microreboot (arXiv:2604.09963) | U |
| Agents | STRATUS (arXiv:2506.02009), TAMO (arXiv:2504.20462) | U |
| Agents / benchmark | ITBench | U (find the reference) |
| RCA, GNN | Gao et al. (arXiv:2501.02766), Buljic (arXiv:2609.27069), Sage (arXiv:2112.06263), survey (arXiv:2407.01710) | U |
| RL, recovery | CRRL (arXiv:2607.03177) | U |
| Industry, blast radius | Netflix ChAP (arXiv:1905.04648), Monocle, Kayenta | U (ChAP read in full in our notes) |
| Industry, mitigation | Meta Maelstrom (OSDI 2018), Microsoft Narya (OSDI 2020), Gandalf (NSDI 2020) | U (secondhand in our notes; read the originals) |
| Benchmark systems | Train Ticket (IEEE TSE 2021), DeathStarBench, Online Boutique | U |

Our own notes with more candidates and a confidence ledger: `docs/research/01-prior-art-and-novelty.md` (sections 2.1 to 2.6 and 4). They were
written with an AI assistant and parts come from search snippets only, so treat every item as a lead, not as a fact.

## Planned structure (target about 8 pages; adjust to the venue template)
1. **Introduction** (0.75 p): why remediation needs evaluation; RQs; contributions (taxonomy, comparison, gap analysis).
2. **Background** (0.5 p): microservice incidents, remediation actions, blast radius.
3. **Method of the survey** (0.75 p): scope, search, screening, numbers (PRISMA-style counts), threats.
4. **Landscape** (1.5 p): the systems and benchmarks, grouped (diagnosis benchmarks, remediation benchmarks, agent environments, learned/risk-aware
   remediation, industrial safe-change systems). Figure: timeline or grouping map.
5. **Comparison** (2 p): the main table (axes above), then one subsection per axis with what we found.
6. **Safety mechanisms** (1 p): sandbox vs policy vs constrained learning vs prediction; what each can and cannot catch.
7. **What is not measured** (0.75 p): collateral damage, time scale of effects, transfer across systems, label validity; what a benchmark would need.
   One paragraph on ARC as an example of a dataset of this kind, disclosed as ours.
8. **Threats to validity** (0.25 p): our search, our reading, preprints.
9. **Conclusion** (0.25 p).

## What we expect to find (hypotheses to test, not claims yet)
- Most benchmarks score whether the incident was resolved; few measure effects on other services.
- Many evaluate in simulated or scripted outcomes rather than on live clusters.
- Metrics differ, so results across papers cannot be compared.
- Safety is mostly a policy gate or sandbox, rarely a prediction of the action's effect.
If the table says otherwise, the paper says otherwise.

## Work split (3 student authors, guide reviews)
- Each author takes about a third of the seed list plus what the search adds, reads the full papers, and fills the table rows with page or section
  references for every entry (so nothing is filled from memory or from an AI summary).
- One author owns the search log and the screening numbers.
- One author owns the figures and the final table layout.
- The assistant can help: find candidate papers, check that references exist and match (arXiv/OpenAlex lookup), format the table and LaTeX,
  draft text from the filled table, and check the numbers. It does not replace reading.

## Timeline (INDIACom paper deadline 7 Dec 2026; the data paper goes to MSR, so this survey must go to a different venue)
| Dates | Goal |
|---|---|
| 2 to 6 Nov | Agree scope and axes with the guide; run the searches; log hits |
| 9 to 15 Nov | Screening; read the seed papers; first fill of the table |
| 16 to 22 Nov | Finish the table; write sections 4 to 6 |
| 23 to 29 Nov | Write sections 1 to 3 and 7 to 9; figures |
| 30 Nov to 3 Dec | Guide review; plagiarism and AI-detection check; fix references |
| 4 to 6 Dec | Submit (INDIACom 7 Dec); fallback IICIT 15 Dec |

## Rules for this paper
- Read before you cite. Every reference must be checked to exist, with the same title, authors and year (lookup tool plus your own check).
- Any text drafted or edited with an AI assistant must be disclosed in the acknowledgments, as the venue asks.
- No copied sentences from the papers; paraphrase and cite. Run the plagiarism check before the guide's final read.
- Be neutral about ARC: it is one row, marked as ours.

## Open questions for the guide
1. Is a survey/comparison paper acceptable for the project requirement, and which authors?
2. Which venue: INDIACom (7 Dec) or IICIT (15 Dec); the template and page limit are not stated on the call pages we read.
3. Preferred scope: remediation only, or remediation plus diagnosis benchmarks?
