Closes #

## What this adds


## Recipe checklist

Skip this section for foundation work. The full contract is in [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md).

- [ ] Changes are confined to `recipes/NN-slug/`
- [ ] Notebook runs top to bottom offline, with no key and no network
- [ ] Live path is opt-in and uses the same question definitions
- [ ] Every response fixture records its provenance; the notebook states which mode it ran in
- [ ] No claim about Jev's quality, latency, or cost without recorded live inference
- [ ] Fixtures are synthetic, include the hard cases, and carry gold labels
- [ ] Python owns every side effect; actions are simulated
- [ ] Evaluation against gold labels, with the baseline the issue names
- [ ] Every acceptance criterion on the issue is met

## How it was verified

