from __future__ import annotations

import json

from banksia.interfaces.http.openapi import build_product_openapi_document

if __name__ == "__main__":
    print(json.dumps(build_product_openapi_document(), indent=2, sort_keys=True))
