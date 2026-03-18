# Example 1: Allow With No Drift

User request:

> Review this single-file change and summarize the main bug risk.

Expected behavior:

- Precheck stays below high risk.
- Do not invoke `token-guard`.
- Proceed normally.
- End with the standard Token Guard estimate line only if this skill was explicitly invoked.
