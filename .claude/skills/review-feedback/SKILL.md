---
name: review-feedback
description: How to evaluate and respond to PR review comments, especially from bots (CodeRabbit, Copilot) — classify, apply or push back, commit per fix, reply tersely. Use when the user asks to address, reply to, or resolve review comments.
---

# Review Feedback

## Default stance on bot comments: skeptical

Bots don't know this codebase's preferences: fail-fast over defensive code,
trust a guarantee once, don't expand scope, churn has a cost.

## Classify before acting

1. **Real bug** — you can name the input that breaks it. **Apply.**
2. **Meaningful improvement** with evidence. **Apply.**
3. **Defense-in-depth where a guard already exists** (schema, DB constraint,
   framework). **Push back.** Exception: if the only enforcement is an opaque
   error deep in the stack, an explicit error naming the contract is correct.
4. **Cargo cult / doesn't apply at this call site.** **Push back.**
5. **Wrong** — misread the code or would regress. **Push back, cite
   file:line.**
6. **Out of scope** — real but not this PR. **Push back; note as follow-up.**

Apply only if you can truthfully finish, in ≤15 words: *"Without this change,
[specific input] produces [specific wrong behavior]."* If it needs "might" or
"could", push back.

Reject by default: silent skip paths, `try/except` around fail-fast code,
`or ""` fallbacks on guaranteed fields, new constraints/migrations the PR
wasn't about, refactor/rename suggestions with no concrete win.

## Fixing

- One fix = one commit, message naming the concern
  (`Review fix: <summary>`). No unrelated changes in it.
- Per comment: read code → decide → edit → lint → targeted test → commit →
  reply citing the SHA.
- Push-backs produce no commit; the reply is the artifact.
- Don't rewrite pushed history unless asked.

## Replying

Terse and honest. No reflexive "Good call" / "Agreed". State the confirmed
failure mode and SHA, or why it doesn't apply (cite the existing guard). Never
apologize for pushing back.

**Never resolve a human reviewer's thread** — reply and leave it for them.
Bot threads may be resolved after replying.

## PR description

When fixes materially change behavior, rewrite the affected bullets in place.
No "Updates since review" section — the description is the current state; the
history is in commits and threads.
