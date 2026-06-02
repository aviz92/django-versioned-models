import json
import urllib.request
import xmlrpc.client

from custom_python_logger import get_logger

logger = get_logger(__name__)

DEFAULT_IGNORE: list[str] = [
    "python-test-aviz",
    "python-pandas-translation",
    "python-llm-factory",
]


def get_user_packages(user: str) -> list[str]:
    """Fetch all package names owned by a PyPI user.

    Args:
        user: The PyPI username to query.

    Returns:
        Sorted list of package names owned by the user.
    """
    client = xmlrpc.client.ServerProxy("https://pypi.org/pypi")
    roles: list[list[str]] = client.user_packages(user)
    return sorted({pkg for _, pkg in roles})


def get_latest_version(package: str) -> str:
    """Fetch the latest published version of a PyPI package.

    Args:
        package: The PyPI package name.

    Returns:
        The latest version string (e.g. "1.2.3").

    Raises:
        urllib.error.URLError: If the PyPI API request fails.
        KeyError: If the response JSON is missing expected fields.
    """
    url = f"https://pypi.org/pypi/{package}/json"
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
        data = json.load(response)
    return data["info"]["version"]


def fetch_user_packages(user: str, ignore: list[str]) -> list[tuple[str, str]]:
    """Fetch latest versions for all packages owned by a PyPI user.

    Skips packages listed in `ignore`. Logs a warning (with traceback)
    for any package whose version cannot be fetched, and continues.

    Args:
        user: The PyPI username to query.
        ignore: Package names to skip.

    Returns:
        List of (package_name, version) tuples for successfully fetched packages.
    """
    packages = get_user_packages(user)
    results: list[tuple[str, str]] = []

    for pkg in packages:
        if pkg in ignore:
            logger.debug("Skipping ignored package: %s", pkg)
            continue
        try:
            version = get_latest_version(pkg)
            results.append((pkg, version))
            logger.info("Fetched: %s==%s", pkg, version)
        except Exception:
            logger.exception("Failed to fetch version for: %s", pkg)

    return results
