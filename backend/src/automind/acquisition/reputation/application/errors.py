"""The failure every reputation store reports (ports of `baseline`, `rollup`, `signals`): its database could not be
read or written. Raised by the infrastructure with the driver's error chained; the services let it propagate."""

from __future__ import annotations


class ReputationStoreUnavailable(RuntimeError):
    """A reputation store could not read or write (its database); the cause is chained."""
