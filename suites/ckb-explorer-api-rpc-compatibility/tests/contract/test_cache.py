from ckb_api_compat.models import RequestCase
from tests.contract_support import LiveContractTestCase, V1_HEADERS


class CacheContractTests(LiveContractTestCase):
    # TP-COMPATIBILITY-API-CONTRACT-027
    def test_tp_027_cold_and_warm_cache_body(self) -> None:
        case = RequestCase("CACHE-WARM", "MOD-API-CONTRACT", "GET", "/v1/statistics", "cache warm", headers=V1_HEADERS)
        self.assert_case(case)
        self.assert_case(case)

    # TP-COMPATIBILITY-API-CONTRACT-028
    def test_tp_028_cache_control_and_conditional_request(self) -> None:
        result = self.assert_case(RequestCase("CACHE-CONTROL", "MOD-API-CONTRACT", "GET", "/v1/statistics", "cache control", headers=V1_HEADERS, selected_headers=("content-type", "cache-control")))
        etag = result.baseline.headers.get("etag")
        if etag:
            headers = dict(V1_HEADERS)
            headers["If-None-Match"] = etag
            self.assert_case(RequestCase("CACHE-ETAG", "MOD-API-CONTRACT", "GET", "/v1/statistics", "etag", headers=headers))

    # TP-COMPATIBILITY-API-CONTRACT-029
    def test_tp_029_cache_key_isolation(self) -> None:
        for page in (1, 2, 1):
            self.assert_case(RequestCase(f"CACHE-PAGE-{page}", "MOD-API-CONTRACT", "GET", "/v1/blocks", "cache key", headers=V1_HEADERS, query={"page": page, "page_size": 1}))
