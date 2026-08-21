PRODUCT_API_PREFIX = "/api"


def build_product_api_path(path: str) -> str:
    """Return the absolute product API path for one root-relative operation."""

    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("product API paths must be root-relative")
    return f"{PRODUCT_API_PREFIX}{path}"


__all__ = ["PRODUCT_API_PREFIX", "build_product_api_path"]
