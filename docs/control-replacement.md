# Replacing the open-weights control

**Status: proposed 2026-11-07, not yet decided.** When it is decided, the outcome goes into
PLAN.md section 2.2 and `drift/panel.yaml` with its date, and this page records why.

## What happened

`openweights-control` called `meta-llama/Llama-3.3-70B-Instruct-Turbo` on Together's
serverless tier. Together took the model off serverless on 2026-10-22, by community reports
of its deprecations page (not yet confirmed from Together's own page). On 2026-11-01 all 2,100
of the control's calls came back:

```
400 model_not_available: Unable to access non-serverless model
meta-llama/Llama-3.3-70B-Instruct-Turbo. Please visit ... to create and start a new
dedicated endpoint for the model.
```

Drift is declared only on a change larger than both the arm's own same-day floor and the
control's change over the same two runs. With no control in November, no arm could be judged
for 2026-10 to 2026-11, and none can be for 2026-11 to 2026-12 either, whatever replaces it:
the replacement has no November run. **The first month a new control can judge is January
2027**, against December.

## What the control is for, and so what a replacement must keep

PLAN.md section 2.2: infrastructure and provider noise with the weights held constant. So:

1. **Weights that cannot change**, named by a checkpoint hash.
2. **Served by a third party per call**, so it carries the kind of serving noise the vendor
   arms carry. Self-hosting would measure our own stack instead.
3. **Cheap enough to run every month** at 2,100 calls.
4. **Not a single point of failure.** One host retiring one model cost a whole month.

## Who serves the same weights per call, checked 2026-11-07

From the public model lists (DeepInfra and Novita) and OpenRouter's endpoint list for
`meta-llama/llama-3.3-70b-instruct`. The cost column applies each listed price to the
control's actual token use in October (968,156 in, 242,373 out); Together charged US$1.26.

| Host | Identifier | Serving | US$ per M in / out | Per run |
|---|---|---|---|---|
| DeepInfra | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | FP8 | 0.10 / 0.32 | about US$0.17 |
| Novita | `meta-llama/llama-3.3-70b-instruct` | not stated | 0.135 / 0.40 (third-party tracker) | about US$0.23 |
| Groq | `llama-3.3-70b-versatile` | own hardware | 0.59 / 0.79 | about US$0.76 |
| CoreWeave, Vertex, SambaNova, Parasail, AkashML, Cloudflare | via OpenRouter | mixed | 0.20 to 0.72 in | |

Prices move; read them again from each host's own page on the day of the decision.

## Options

- **A. The same weights on another host, per call (proposed).** DeepInfra serves the same
  checkpoint in FP8, as Together's Turbo did, through an OpenAI-compatible API, which is the
  `openai_compat` kind boundary already speaks to. About an eighth of what Together charged.
  The series does not continue: a different host is a different serving stack, which is
  exactly what the control measures, so it is a new arm with a new key.
- **B. A Together dedicated endpoint.** Keeps the host, but billed by the hour while it is up,
  and a dedicated endpoint is still a different serving stack from serverless. Pays more and
  still breaks the series. Rejected.
- **C. Self-host on rented GPUs.** The most frozen option, but it measures our own vLLM and
  hardware, not a provider's, so it stops being the comparison the vendor arms need. Rejected.
- **D. A newer open-weights model on Together's serverless tier** (for example the
  replacement Together names). Same host, but the same thing can happen again, and a new model
  breaks the series just as A does. No advantage over A.

## Proposal

1. **Primary control: DeepInfra, `meta-llama/Llama-3.3-70B-Instruct-Turbo`**, same
   `weight_hash` as before (`6f6073b4...`, the Hugging Face commit read 2026-09-12). New
   provider `deepinfra` in `drift/config/boundary.yaml`, arm key `deepinfra-control`, a
   `DEEPINFRA_API_KEY` secret, and its price in a new price file.
2. **A standby control on a second host: Novita**, the same weights, arm key
   `novita-control`, run every month at about US$0.23. The rule is fixed now, before any
   result: drift is judged against the primary; if the primary did not answer in both runs,
   against the standby; if neither did, not judged. Written down before a month needs it, so
   it cannot be chosen after seeing which control gives the answer.
3. **Retire `openweights-control` from the panel** in December with a dated note. PLAN.md
   says a retired identifier keeps being called and the error is the result; November's
   2,100 errors are that result, and calling it again records nothing new.
4. **Say in the README** that December cannot be judged and why, before the run.

Cost: about US$0.40 a month for both controls against US$1.26 for Together's, so the panel
gets cheaper.

## What is already in place

- The rule says "not judged" instead of "no" when the control is missing (`drift_judged`,
  2026-11-07), on the report, the README and the site.
- `drift panel preflight`, run by the monthly workflow before any vendor job: one short call
  per arm. A failed vendor arm is printed and the run goes ahead; a failed control stops the
  run before anything is spent. **Until the control is replaced, the December run will stop
  at this step**, which is intended: fix the panel, then rerun within the 72 hours PLAN.md
  section 8 allows.

## To do once decided

- Live smoke call to each new host through boundary (the smoke workflow's `extra_models`).
- `panel.yaml`, boundary config, price file, secrets.
- The standby rule in `drift_calls` and the report (today they know one `control_key`).
- PLAN.md 2.2 and the section 8 risk table: "the control's host retires it".
