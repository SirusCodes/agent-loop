# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.291 | +23.6% | 0.202 | +11.3% | 0.506 | +8.2% | 39% | 73 (348) |
| nw_kyc | 0.365 | -2.2% | 0.234 | -0.1% | 0.597 | -1.9% | 10% | 32 (29) |
| nw_renewal | 0.383 | -11.5% | 0.267 | +1.8% | 0.485 | -12.6% | -47% | 26 (54) |
| ALL | 0.338 | +2.1% | 0.231 | +5.0% | 0.515 | -3.3% | -9% | 131 (431) |

## Changes applied by the controller

5 applied — harmful: 2, beneficial: 3

- nw_renewal v2 (controller_approved) dims=['prompt_version'] engageΔ=-0.139 didΔ=+0.000 → **harmful**
- ks_cancel v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.480 → **beneficial**
- ks_cancel v4 (controller_approved) dims=['prompt_version'] engageΔ=+0.157 didΔ=+0.000 → **beneficial**
- ks_cancel v5 (controller_approved) dims=['prompt_version'] engageΔ=-0.018 didΔ=+0.000 → **harmful**
- nw_kyc v2 (controller_approved) dims=['prompt_version'] engageΔ=+0.031 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 5,
  "decisions": {
    "approved": 5,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 5,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "ks_cancel": 2,
    "nw_kyc": 1
  }
}
```

## Incidents

```
[
  {
    "type": "did_flagged",
    "workflow": "ks_cancel",
    "at": "D2 10:00",
    "flagged_did_share_by_day": {
      "2": 0.25,
      "3": 0.0,
      "4": 0.0,
      "5": 0.0,
      "6": 0.0,
      "7": 0.0,
      "8": 0.0,
      "9": 0.0
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 1470,
    "fixed_by": "controller_approved"
  },
  {
    "type": "supervisor_edit",
    "workflow": "nw_renewal",
    "at": "D5 15:00"
  }
]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{}
```

Credits used: 30 · validation runs: 6 · LLM fix calls: 6