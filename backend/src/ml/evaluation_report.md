# Renvue recovery policy — offline evaluation

Generated: 2026-11-02T21:33:09  
Dataset hash: `68e446fa555a07de`  
Policy: `policy-0.1-ev`  

> **Simulated data.** This report evaluates a policy on a calibrated synthetic
> simulator with potential outcomes. It is not a production lift claim.

## Dataset

- Training decisions: 54,000
- Validation decisions: 6,000
- Held-out episodes: 10,000
- Held-out potential outcomes: 90,000
- Mechanisms: reason-driven and persona-driven
- Held-out personas: {'reason': ['serial_ptp'], 'persona': ['dispute_prone']}

## Propensity model (M1)

| Metric | Value |
|---|---:|
| AUROC | 0.745 |
| AUPRC | 0.356 |
| Brier | 0.129 |
| ECE (10 bins) | 0.003 |
| Validation paid rate | 17.8% |

Unbiased RCT check (uniform action assignment):

| AUROC | AUPRC | Brier | ECE | Paid rate |
|---:|---:|---:|---:|---:|
| 0.771 | 0.310 | 0.096 | 0.014 | 12.2% |

## Policy comparison — held-out worlds

| Policy | Net / 1,000 | 95% CI | Recovery | Cost / recovery | Time to pay | Opt-out | Dispute |
|---|---:|---|---:|---:|---:|---:|---:|
| `no_contact` | $30,224 | $26,790–$34,086 | 7.5% | $1.99 | nand | 0.23% | 0.20% |
| `rules` | $120,305 | $111,470–$129,548 | 23.4% | $2.12 | nand | 0.36% | 0.38% |
| `ml_ev` | $120,311 | $111,582–$129,633 | 23.6% | $1.91 | nand | 0.52% | 0.42% |
| `ml_no_guardrails` | $120,614 | $111,898–$129,813 | 23.8% | $1.80 | nand | 0.52% | 0.42% |
| `oracle` | $124,081 | $115,176–$133,106 | 25.1% | $0.84 | nand | 0.25% | 0.22% |

### Incremental lift

- ML vs rules: **$7 / 1,000** (95% CI $-878 to $980)
- Rules vs no-contact: **$90,080 / 1,000**
- ML vs no-contact: **$90,087 / 1,000**
- Oracle gap closed: **0.18%**

## By mechanism

| Mechanism | Policy | Net / 1,000 | Recovery |
|---|---|---:|---:|
| reason | `rules` | $108,012 | 23.7% |
| reason | `ml_ev` | $106,695 | 23.4% |
| reason | `oracle` | $111,025 | 24.9% |
| persona | `rules` | $132,598 | 23.2% |
| persona | `ml_ev` | $133,928 | 23.9% |
| persona | `oracle` | $137,137 | 25.3% |

## Sensitivity grid

| Response curve | No-contact | Rules | ML | Oracle | ML rank |
|---|---:|---:|---:|---:|---:|
| optimistic | $32,813 | $136,686 | $136,156 | $140,220 | 2 |
| base | $33,894 | $122,223 | $121,830 | $126,082 | 2 |
| pessimistic | $37,016 | $112,440 | $111,969 | $116,436 | 2 |

## Guardrails

- ML proposals changed by deterministic guardrails: 1164 (11.64% of cases)
- Guardrails can veto, downgrade, or defer; the executor only runs the approved Play.

## What this proves

- The policy learns heterogeneous action effects in two held-out mechanisms.
- The rules baseline and ML policy share the same feature, eligibility, and guardrail contracts.
- Decision logs contain the feature snapshot, alternatives, chosen Play, and outcome.

## What this does not prove

- It does not prove lift on real PayPal merchants.
- It does not show that the simulator's response functions match reality.
- It does not replace a production causal evaluation or legal/compliance review.
