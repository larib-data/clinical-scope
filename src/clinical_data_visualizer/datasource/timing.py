"""
Performance timing decorator for datasource operations.

This module provides the ``time_it`` decorator used to measure and log
execution time of datasource methods (_load, _format, _find, etc.).

The decorator is datasource-centric because it primarily decorates datasource
methods rather than being a general-purpose utility used across the codebase.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


# ==================================================================================================
def time_it(func: Callable) -> Callable:
    """Decorator to measure and log execution time using import-style function identifier."""

    def arg_wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()

        func_name = func.__name__
        try:
            module_name = func.__module__
        except AttributeError:
            module_name = "Unknown"

        logger.debug("%.3fs to run %s from %s", end - start, func_name, module_name)
        return result

    return arg_wrapper
