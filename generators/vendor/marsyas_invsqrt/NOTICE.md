# Attribution and provenance

Module bodies extracted from Houssem Alayet (marsyas),
`VQCC invsqrt 13.94x - full source`, Kaggle notebook version 2,
retrieved 2026-10-30. The notebook explicitly releases this code under
Apache License 2.0. The notebook `%%writefile` directives were removed and
one terminal LF was appended by the export. All other module bytes are unchanged.
Both original-body and exported hashes are retained in manifest.json.

Source: https://www.kaggle.com/code/marsyas/vqcc-invsqrt-13-94x-full-source
Kaggle notebook id 140607518, version 2; exact module hashes are in manifest.json.

Upstream states that the following ideas were independently reimplemented:
Sumit Chongder and kozykappa (signed-digit rows), anazemcev (high/low split,
exact compilation), Dmitrii Gluzdov (merged unlookup), Artem (exact-domain
pass), auqib92 (nested windows), mizeroluckygall and lightningv08 (angle
calibration), rudrabhaskar (direct polynomial phasing).
Google Quantum AI provides the separately licensed, unchanged kickmix and
verifiers used by the project. No upstream notebook packaging or submission
cells are executed by the local adapter.

Raw notebook and metadata are archived under
`artifacts/runs/20261030T121300-optimize-06826d/research/marsyas-v2.json`.
The local adapter is `generators/invsqrt_piecewise.py`.
