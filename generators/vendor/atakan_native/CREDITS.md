# Current v2 chemistry bank: attribution overrides

This bank contains chemistry ANGLE circuits, coefficient plans and the selected
participant factorization only. It contains neither DQI nor inverse-square-root
generators. Historical full-portfolio statements below do not describe this
bank's selected assets, current weights or DQI policy.

Selected factor SHA256: `fa84c57c00f137eb0633d07a487e154d234d2c1e92a44dc42f849b04ef60ab37`.
Selection/producer note: Three credited native ANDs/pass saved versus own-v3: Heliosli V20/run363468177 supplies angle1/8 reductions; Dmitrii Gluzdov V34/run363471947 supplies a distinct angle2 reduction. Their product structures were authenticated and recovered, then emitted by our producer against our unchanged46-word learned table and physical/LP-refitted weights. Gate reductions are inherited, not claimed as our invention. Own contribution is constrained angle/factor training, monotone joint LP weights, controlled selection, exact plan recovery/rebuild and compatibility/phase verification.4170AND/pass,16270T430Q, full seeds20261029173/174, fixed896Q DQI kept in the separate portfolio. Estimated22.8044959 is not a new observed public score.

The selected W and H2_I are the explicit local derivative named in the manifest.
Their lineage includes our compiler-constrained angle/factor co-design, the
QR-barrier math/reproduction credited to Ahmed Berat Ozer and mrmeows, and any
final exact-pair refinement identified by the supplied producer evidence.
They are not asserted byte-for-byte identical to Dmitrii's upstream weights.

Credit Kirill Tymchishin for the adapted exact sign-boundary pair minimizer;
the earlier orthogonal-gauge lineage includes Kozykorpesh, mrmeows, Alex Chilton,
Ahmed Ozer and Phuc Thai. Our CPU/GPU compositions and verification work are
separate from invention of those public identities or optimizers.

Dmitrii Gluzdov supplies the inherited seed factor/angle family. Heliosli's
compiled loader structures are recovered as attributed inputs. SomeJoint's
split-ANF/paired-product/full-XOR design and public redundant-sign borrowing
are prior art. Our current native files are emitted by our own source generator
from those inherited structures with our recorded angle/weight changes.

Exported proof/producer source files retain their author terms. Supplied
Ahmed/mrmeows/Kirill licence and notice texts are copied under notices/ and
hash-listed in SOURCE_MANIFEST.json. This exporter grants no blanket licence
over upstream proof code. Original notices embedded in source files remain.

## Historical upstream full-portfolio credits — verbatim

The following is retained solely as historical provenance. In particular,
"ours", "895-qubit DQI", "byte for byte" weights, and "all fifteen angle
circuits are ours" refer to that upstream document's authors and old portfolio,
not to exclusive authorship or byte identity of this selected v2 bank.

# Sources and credits

- **invsqrt** — Akmal Xodarev's (busyaprime) newest file from https://www.kaggle.com/datasets/busyaprime/33-qcc-v8-members
  (Apache-2.0; notebook https://www.kaggle.com/code/busyaprime/lb-22-72431-22x-cheaper-than-google-s-circuits),
  byte for byte: mrmeows' (team selenium) 63-qubit build (https://www.kaggle.com/datasets/mrmeows/qcc-1375-open-circuits,
  Apache-2.0) with two regions rebuilt by busyaprime. Lineage as they name it: Akmal Xodarev (busyaprime), Phuc
  Thai (DePie), Dmitrii Gluzdov, marsyas.
- **dqi** — Mudit Chaturvedi's (muchat007) 895-qubit streamed decoder
  (https://www.kaggle.com/code/muchat007/895q-streamed-decoder-measured-node-choices, Apache-2.0), byte for byte, the
  file as shipped in the output of manwithacat's https://www.kaggle.com/code/manwithacat/the-real-150k-was-the-friends-we-made.
  It is built on SomeJoint's streamed decoder and source package
  (https://www.kaggle.com/code/somejoint/quantum-circuits-22-75-local-gm-897-qubit-dqi). Earlier decoder line:
  SomeJoint's research team and GPT-6 Astra Pro; Ahmed Berat Özer; Alex Chilton's 883-qubit Schur decoder, based on
  jday96314's QuantumAI decoder (https://github.com/jday96314/QuantumAI); mrmeows, Ahmed Berat Özer and manwithacat
  (mask projection); Dmitrii Gluzdov, Agniv Banerjee (SomeJoint), ViberTeam, Phuc Thai (DePie). Atakan Aldemir and
  Alex Chilton published portfolios with it first.
- **dfthcsos** — SomeJoint's (Agniv Banerjee's team) R = 8, B = 143, C = 60 factorization and angle circuits from
  https://www.kaggle.com/datasets/somejoint/qcc-our-chemistry-b143-c60-xor2 (Apache-2.0; notebook
  https://www.kaggle.com/code/somejoint/quantum-circuits-22-67-local-gm-full-xor-chem): the factors and angle words of the
  factorization file. Lineage as that notebook names it: Michael Rustad, Ahmed Berat Özer,
  Akmal Xodarev (busyaprime), Vladislav Lavrentev (lightningv08), mrmeows. All fifteen angle circuits are ours,
  on SomeJoint's design.
  The table weights (W, H2_I) are Dmitrii Gluzdov's, byte for byte, from the output of
  https://www.kaggle.com/code/dmitriigluzdov/quantum-circuit-compilation-from-source (Apache-2.0).
- **Organizers** — task definitions, verifiers and kickmix (Google Quantum AI / Qualtran, competition data).
