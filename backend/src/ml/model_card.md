# Renvue recovery policy — model card

## Model

- Name: `policy-0.1` / `lgbm-2026-11-02`
- Type: M1 calibrated LightGBM propensity + M2 LightGBM T-learner per Play
- Training rows: 54,000 simulated decisions
- Dataset hash: `68e446fa555a07de`
- Trained: 2026-11-02T15:57:06.608744+00:00

## Intended use

Choose one of eight recovery Plays (or `no_contact`) for a failed PayPal payment,
failed subscription, abandoned checkout, or overdue invoice. The Play is scored by
expected net recovered dollars. Deterministic guardrails have final veto.

## Action space

`no_contact`, `email_link`, `sms_link`, `paypal_invoice_reminder`, `retry_now`,
`retry_payday`, `update_method_link`, `discount_link`, `human_escalation`.

## Features

Only fields in the locked `Observation` contract are used: amount, currency, days
past due, failure class/code, payment method and age, attempts, contact count and
recency, prior payments/failures/recoveries, tenure, segment, dispute/opt-out flags,
local hour/weekday, month-end proximity, payday signal, and invoice age.

Latent simulator fields (`persona`, `p_pay_true`, counterfactual outcomes) never
enter the feature frame. `FEATURE_ALLOW_LIST` is the boundary.

## Training data

A synthetic simulator calibrated to published ranges: involuntary churn roughly
5–15%, B2C recovery roughly 25–40%, hard declines near zero without a method change,
and retry success declining with attempts. Parameters are tagged `sourced` or
`assumption` in the simulator; the sensitivity grid varies the assumption-heavy
response curves.

Two mechanisms are generated: a reason-driven world and a persona-driven world.
Training uses worlds 1–3 and validation world 4. Final evaluation uses world 5 with
held-out personas. The training log is deliberately confounded; a uniform RCT log is
kept for estimator validation and is not used for training.

## Metrics

| Metric | Value |
|---|---:|
| Validation AUROC | 0.745 |
| Validation AUPRC | 0.356 |
| Validation Brier | 0.129 |
| Validation ECE | 0.003 |
| ML net / 1,000 (held out) | $120,311 |
| Rules net / 1,000 (held out) | $120,305 |
| No-contact net / 1,000 | $30,224 |
| Oracle net / 1,000 | $124,081 |

## Limitations

- No real merchant training data. The simulator is a test rig, not evidence of
  production lift.
- Response functions are assumptions. The sensitivity grid reports policy rank across
  optimistic/base/pessimistic curves.
- The live PayPal sandbox proves execution and logging, not statistical lift.
- The current policy is a one-step decision policy replanned after every event; it is
  not a full sequence model.
- A production deployment needs legal/compliance review, merchant-specific calibration,
  and monitoring for opt-out/dispute harm.

## Ethical and consumer-protection notes

- Opt-out and dispute freeze are hard stops in the guardrail layer.
- Discounts are capped and scoped to abandoned checkouts.
- Contact frequency and contact windows are enforced in code, not learned.
- No protected attributes or demographic proxies are features.
