from __future__ import annotations

import argparse
import json

from oh_my_subagents.interfaces.http.openapi import (
    PRODUCT_PATHS,
    SUPPORT_PATHS,
    build_openapi_document,
    build_product_openapi_document,
    build_support_openapi_document,
    validate_openapi_separation,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--surface",
        choices=("product", "support"),
        default="product",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            build_openapi_document(args.surface),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()


__all__ = [
    "PRODUCT_PATHS",
    "SUPPORT_PATHS",
    "build_openapi_document",
    "build_product_openapi_document",
    "build_support_openapi_document",
    "main",
    "validate_openapi_separation",
]
