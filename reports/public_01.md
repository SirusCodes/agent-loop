# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.345 | +1.0% | 0.244 | -0.1% | 0.497 | +1.0% | 1% | 62 (57) |
| nw_kyc | 0.409 | +11.6% | 0.248 | +2.6% | 0.642 | +7.6% | 29% | 31 (21) |
| nw_renewal | 0.426 | +2.3% | 0.262 | -0.9% | 0.558 | +2.9% | 9% | 41 (54) |
| ALL | 0.386 | +3.7% | 0.251 | +0.1% | 0.547 | +3.2% | 10% | 134 (132) |

## Changes applied by the controller

6 applied — beneficial: 5, harmful: 1

- nw_kyc v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.075 didΔ=+0.000 → **beneficial**
- nw_renewal v2 (controller_approved) dims=['prompt_version'] engageΔ=+0.031 didΔ=+0.000 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.028 didΔ=+0.000 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['welcome_message'] engageΔ=-0.015 didΔ=+0.000 → **harmful**
- nw_kyc v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**
- ks_cancel v2 (controller_approved) dims=['prompt_version'] engageΔ=+0.050 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 8,
  "decisions": {
    "approved": 6,
    "rejected": 2,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 6,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_kyc": 1,
    "nw_renewal": 1,
    "ks_cancel": 1
  }
}
```

## Incidents

```
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{}
```

Credits used: 10 · validation runs: 2 · LLM fix calls: 2