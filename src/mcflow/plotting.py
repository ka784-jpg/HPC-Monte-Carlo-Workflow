"""Optional plotting; simulation and validation have no third-party dependencies."""

import math
from pathlib import Path

from .analysis import aggregate
from .storage import WorkflowError


def plot(run):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import ScalarFormatter
    except ImportError as exc:
        raise WorkflowError('Install plotting support: python -m pip install -e ".[plots]"') from exc

    summary = aggregate(run)
    groups = summary["groups"]
    sizes = [group["samples_per_replicate"] for group in groups]
    means = [group["pi_estimate"] for group in groups]
    errors = [[g["pi_estimate"] - g["ci95_low"] for g in groups],
              [g["ci95_high"] - g["pi_estimate"] for g in groups]]
    style = {"font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
             "axes.labelcolor": "#272727", "text.color": "#272727", "axes.titleweight": "bold"}
    with plt.rc_context(style):
        fig, (left, right) = plt.subplots(1, 2, figsize=(11.8, 4.4), layout="constrained")
        left.errorbar(sizes, means, yerr=errors, fmt="o-", color="#167d9a", capsize=5,
                      linewidth=1.8, label="Pooled estimate + 95% Wilson CI")
        left.axhline(math.pi, color="#c25b25", linestyle="--", linewidth=1.6, label=r"Exact $\pi$")
        left.set(xscale="log", xlabel="Samples per replicate", ylabel=r"Estimate of $\pi$",
                 title="A. Estimate and uncertainty")
        left.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        right.loglog(sizes, [g["replicate_rmse"] for g in groups], "o-", color="#167d9a",
                     linewidth=1.8, label="Measured replicate RMSE")
        right.loglog(sizes, [g["theoretical_single_run_se"] for g in groups], "--",
                     color="#c25b25", linewidth=1.6, label=r"Theory $\propto N^{-1/2}$")
        right.set(xlabel="Samples per replicate", ylabel="Single-replicate error",
                  title="B. Monte Carlo convergence")
        for axis in (left, right):
            axis.grid(alpha=0.18)
            axis.legend(frameon=False, fontsize=9, loc="best")
        fig.suptitle(f"Quarter-circle Monte Carlo | {groups[0]['replicates']} replicates per budget",
                     fontsize=14, fontweight="bold")
        output = Path(run) / "analysis"
        fig.savefig(output / "convergence.png", dpi=180, facecolor="white")
        fig.savefig(output / "convergence.pdf", facecolor="white")
        plt.close(fig)
    return output / "convergence.png"
