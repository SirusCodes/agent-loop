# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.342 | +1.4% | 0.246 | +1.2% | 0.497 | +0.2% | 0% | 402 (409) |
| arav_kyc_1 | 0.368 | +2.6% | 0.214 | -0.5% | 0.615 | +2.4% | 18% | 340 (352) |
| arav_renewal_0 | 0.426 | +5.1% | 0.264 | -0.0% | 0.574 | +4.7% | 23% | 449 (408) |
| kest_cancel_2 | 0.340 | +0.9% | 0.244 | +0.7% | 0.500 | +0.2% | 0% | 388 (418) |
| kest_kyc_1 | 0.371 | +4.4% | 0.214 | -0.1% | 0.619 | +3.6% | 22% | 268 (370) |
| kest_renewal_0 | 0.426 | +5.9% | 0.265 | +0.2% | 0.570 | +4.7% | 22% | 444 (403) |
| nort_cancel_2 | 0.341 | +0.5% | 0.244 | -0.0% | 0.499 | +0.1% | 0% | 400 (368) |
| nort_kyc_1 | 0.380 | +6.9% | 0.215 | -0.1% | 0.633 | +6.3% | 34% | 233 (318) |
| nort_renewal_0 | 0.422 | +4.2% | 0.264 | -0.0% | 0.568 | +3.6% | 17% | 404 (419) |
| tide_cancel_2 | 0.342 | -0.4% | 0.245 | +0.1% | 0.501 | -0.1% | 0% | 401 (401) |
| tide_kyc_1 | 0.380 | +6.7% | 0.214 | -0.2% | 0.632 | +5.6% | 33% | 283 (376) |
| tide_renewal_0 | 0.413 | +2.1% | 0.263 | -0.3% | 0.560 | +2.6% | 11% | 1024 (425) |
| ALL | 0.379 | +3.4% | 0.241 | +0.1% | 0.562 | +2.9% | 16% | 5036 (4667) |

## Changes applied by the controller

15 applied — beneficial: 14, harmful: 1

- nort_kyc_1 v2 (controller_approved) dims=['prompt_version'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v2 (controller_approved) dims=['prompt_version'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['prompt_version'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.068 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v2 (controller_approved) dims=['prompt_version'] engageΔ=+0.049 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.067 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.075 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.075 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.074 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.068 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.074 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.028 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.028 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.027 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v3 (controller_approved) dims=['prompt_version'] engageΔ=-0.047 didΔ=+0.000 → **harmful**

## Governance

```
{
  "approval_requests": 19,
  "decisions": {
    "approved": 16,
    "rejected": 3,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 3
  },
  "applied_via_approval": 15,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nort_kyc_1": 1,
    "tide_kyc_1": 1,
    "kest_kyc_1": 1,
    "nort_renewal_0": 1,
    "kest_renewal_0": 1,
    "arav_renewal_0": 1,
    "arav_kyc_1": 1,
    "tide_renewal_0": 3
  }
}
```

## Incidents

```
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "kest_renewal_0:welcome_message=W3": {
    "4": 0.334
  },
  "arav_renewal_0:welcome_message=W3": {
    "4": 0.338
  }
}
```

Credits used: 35 · validation runs: 7 · LLM fix calls: 7