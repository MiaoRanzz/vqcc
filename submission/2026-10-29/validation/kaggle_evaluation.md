Submissions are evaluated using the geometric mean of each task's improvement relative to a baseline.

$$\text{Score} = \left( \prod_{b=1}^{3} \frac{\text{cost}_b^{\text{ref}}}{\text{cost}_b} \right)^{1/3}$$
 
Each task has a different loss function:

  | Task | Paper | Cost |
  |:---|:---|:---|
  | `invsqrt` (Fusion Energy)| Benchmark I | \\( Q \times C \\), where \\( C = \text{Toffolis} + \text{T gates} / 4 \\) |
  | `dqi` (Combinatorial Optimization)| Benchmark II | \\( R(\epsilon_{+}) \times Q^{2} \times T \\), where \\( R(\epsilon) = \frac{\ln 2}{-\ln\left(\frac{1}{2} + 2\sqrt{\epsilon}\right)} \\) |
  | `dfthcsos` (Quantum Chemistry & Clean Energy)| Benchmark III | \\( \lambda_{\text{eff}} \times T \times Q \\), where \\( \lambda_{\text{eff}} = \sqrt{E_{\text{gap}}\left(2\Lambda - E_{\text{gap}}\right)} \\) |
   
  where \\( Q \\) is the qubit count and \\( T \\) the Toffoli count, both per shot. For `dqi`, \\( \epsilon_{+} \\) is an upper confidence bound on the decoder's failure rate. For `dfthcsos`, \\( T \\) and \\( Q \\) cover the whole block encoding, not just the submitted ANGLE circuits, and any ANGLE circuit wider than 128 qubits is rejected.

## Submission File
You must submit a zip archive containing the following files:
 - `invsqrt.kmb` or `invsqrt.kmx`
 - `dqi.kmb` or `dqi.kmx`
 - a folder named `dfthcsos` containing the circuits `angle_k_0`, `angle_k_1`, … `angle_k_<n-1>`, numbered from 0 with no gaps, each as `.kmb` or `.kmx`, plus `submission.npz` holding the factorization (`U`, `W`, `H2_I`, `H1_I`, `Hsym_lower`) and the Givens tree (`tree_edges`).
  
Scoring takes roughly 45 minutes.

You can review [the full metric implementation here](https://www.kaggle.com/code/metric/google-quantum-ai-metric).
