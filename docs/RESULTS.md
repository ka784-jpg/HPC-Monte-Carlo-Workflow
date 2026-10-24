# Example Results

These are outputs of the public toy model, not research data. The included [configuration](../configs/gallery.json) specifies four sample budgets and 64 replicates per budget, with master seed 2026. All 256 tasks passed validation, totaling 7,110,400 sampled points.

![Convergence of the pi estimate and its sampling error](assets/convergence.png)

[Full-resolution PNG](assets/convergence.png) | [Vector PDF](assets/convergence.pdf) | [Per-task CSV](assets/tasks.csv) | [Validated summary](assets/summary.json) | [Provenance and hashes](assets/provenance.json)

## What Is Being Simulated?

Draw independent uniform points `(x, y)` in the unit square. A point is a hit if `x*x + y*y <= 1`: it lies inside the quarter unit disk. The area ratio is `p = pi/4`, so for `H` hits in `N` trials,

$$\widehat{\pi}=4H/N, \qquad H\sim\mathrm{Binomial}(N,\pi/4).$$

Consequently the estimator is unbiased under the ideal independent-sampling model, with

$$\mathrm{SE}(\widehat{\pi})=\sqrt{\frac{4\pi-\pi^2}{N}}.$$

This exact reference tests the workflow's statistical behavior without requiring any private simulator or dataset. The [sampling kernel](../src/mcflow/engine.py) is intentionally short enough to inspect in full.

## Reading the Figure

**Left:** each point pools hit counts across the 64 replicates at that sample budget. Error bars are 95% Wilson score intervals for the pooled binomial probability, multiplied by four. Thus its effective sample count is `64*N`, not `N`. The dashed line is the exact value of pi. Budgets are separate experiments, not prefixes of one shared trajectory.

**Right:** the measured root-mean-square error is computed across the 64 *individual* estimates at each budget, relative to the exact pi. Its reference curve uses the single-replicate sample count `N`. Agreement with `N^(-1/2)` is the expected Monte Carlo convergence trend, not a speedup benchmark. Connecting lines are guides to the eye.

| Points per replicate | Pooled estimate | Pooled 95% Wilson interval | Individual-replicate RMSE |
| ---: | ---: | --- | ---: |
| 100 | 3.101250 | [3.059694, 3.141485] | 0.184054 |
| 1,000 | 3.146125 | [3.133358, 3.158754] | 0.052197 |
| 10,000 | 3.143869 | [3.139842, 3.147881] | 0.015298 |
| 100,000 | 3.140569 | [3.139295, 3.141841] | 0.005083 |

A confidence interval is not a guaranteed bound. For example, the smallest-budget interval here narrowly misses pi; that is a possible sampling outcome, not a reason to reroll the seed. These are pointwise intervals, not a simultaneous confidence band over all budgets. Estimated RMSE also fluctuates with the finite number of replicates.

## Reproduce

After the [installation steps](../README.md#quickstart):

```bash
python examples/reproduce.py --workers 2
```

The script creates or resumes `runs/gallery`, checks that its manifest matches the public configuration, validates the results, and writes plots and tables under `runs/gallery/analysis`. Use one worker on a single-core machine. Running again skips already valid results.

The checked-in CSV contains every replicate's seed, hit count, estimate, and interval. Compare it with the regenerated `tasks.csv`; numerical counts should match for the tested runtime. The reference export used Python 3.12.14 and Matplotlib 3.11.2. Rendering/font/library changes can alter image bytes without changing numerical results. Python-version metadata also changes the full result-payload hash; it does not change the meaning of the table.

Maintainers can refresh the checked-in figure and its provenance with:

```bash
python examples/export_gallery.py runs/gallery
```

The export command accepts only a run matching `configs/gallery.json` and revalidates it before exporting. It copies a fixed set of public analysis artifacts, never arbitrary campaign directories.

## Confidence Interval Details

For `phat = H/N` and `z` the 97.5th percentile of a standard normal distribution, the Wilson probability interval is

$$\frac{\widehat p+z^2/(2N)\;\pm\;z\sqrt{\widehat p(1-\widehat p)/N+z^2/(4N^2)}}{1+z^2/N}.$$

Multiplying the endpoints by four gives the interval for pi. Unlike a naive plug-in normal interval, this retains nonzero uncertainty when every sample hits or every sample misses. The formula and boundary cases are tested in [test_workflow.py](../tests/test_workflow.py).
