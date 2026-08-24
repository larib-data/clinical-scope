# 6. ClinicalScope derives for display; it does not interpret

Date: 2026-08-07

## Status

Accepted

## Context

ClinicalScope has always been described as a tool that *displays* clinical signals rather than one that *processes* them, but that boundary was never written down — and it is already blurred by shipped behaviour:

- `Signal.loop_from_signals` interpolates two Signals onto a union time grid (`np.interp`) to build a Loop.
- `unit_conversion` scales every sample of a Signal by a configured factor.
- `period_resampling` decimates a Signal before it is ever drawn.

All three compute values the device never recorded. So "we only display" is not literally true, and a contributor who takes it literally will reach the wrong conclusion about what belongs here.

The question became load-bearing with issue #71 (a spectrogram plot type, requested repeatedly for EEG). The request was initially declined as "processing", then reconsidered — not because anyone's position changed, but because there was no stated rule to apply, so the same argument was had twice with different outcomes. Left unstated, every future request re-opens it: band power, seizure detection, arrhythmia classification, artefact rejection, risk scores.

Three options were considered:

1. **Strict display-only** — no computation beyond reading and drawing. Honest and trivially enforceable, but immediately false: it would rule out the Loop, unit conversion, and resampling that already ship, and forbid a spectrogram, which is a rendering of the data rather than a claim about it.
2. **No clinical interpretation** — computation is allowed when it is a deterministic function of Signals already in the pipeline and its output is something to look at, not a conclusion to act on.
3. **Case by case** — judge each request on its merits. Maximum flexibility, no predictability; in practice this is what produced the contradictory answers on #71.

## Decision

2 — **ClinicalScope derives for display; it does not interpret.**

A computation belongs in this library only when both hold:

- it is a **deterministic function** of Signals already in the pipeline, and
- its output is **something to look at**, not a conclusion to act on.

The operational test for a contributor is: **would this output need clinical validation before someone could trust it?** If yes, it belongs in the user's own analysis code, not here. A spectrogram passes — it is a re-rendering of the same samples in a different basis, and a reader draws their own conclusions from it. A seizure detector or a depth-of-sedation score fails: each embeds a clinical judgement that would need validating, and each would make ClinicalScope a device rather than a viewer.

Two properties made this the choice:

- **It matches what already ships.** Option 1 would have required deleting or grandfathering existing features. The Loop, unit conversion, and resampling all pass the test as stated, so the rule describes the codebase rather than contradicting it.
- **It is decidable without a maintainer.** A contributor can apply the validation test to a new request unaided. Option 3 sounds accommodating but pushes every decision back to a conversation, which is how #71 got two different answers.

The rule deliberately says nothing about *how much* computation is acceptable. An FFT is not more suspect than a subtraction; what matters is whether the output is a picture or a verdict.

## Consequences

- **Easier:** feature requests get a fast, citable answer, and the answer is the same whoever gives it. Contributors can self-assess before opening a PR.
- **Declined by this rule, and worth naming so the answers are on record:** seizure and burst-suppression detection, arrhythmia classification, automated artefact rejection, depth-of-sedation or severity indices, and any alerting.
- **Harder / accepted trade-offs:** the line runs close to the boundary in places, and derived *scalars* are the awkward case. Spectral edge frequency and band power are deterministic and are plotted, not asserted — so they pass the test — yet they are also the raw material of the sedation indices this ADR rejects. They were dropped from #71 for scope reasons, not by this rule; if they are proposed later, the test admits them and that is intended.
- **Revisit if:** users need a genuine clinical computation often enough that maintaining it outside ClinicalScope is the greater cost — at which point the answer is a separate, separately validated package, not a relaxation of this rule.
