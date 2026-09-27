"""CarbonScope India.

macOS: LightGBM (Homebrew/wheel libomp) and PyTorch (its own libomp) conflict — torch's intra-op thread pool
segfaults after LightGBM has run. Import lightgbm first and pin torch to 1 thread on darwin (data is tiny).
"""
import sys

try:
    import lightgbm  # noqa: F401
except ImportError:  # optional in API-only containers
    pass
if sys.platform == "darwin":
    try:
        import torch

        torch.set_num_threads(1)
    except ImportError:
        pass
