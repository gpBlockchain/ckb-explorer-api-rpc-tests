from ckb_api_compat.models import RequestCase
from tests.contract_support import LiveContractTestCase, V1_HEADERS


class V1MediaContractTests(LiveContractTestCase):
    # TP-COMPATIBILITY-API-CONTRACT-005
    def test_tp_005_exact_v1_media_headers_dispatch(self) -> None:
        result = self.assert_case(RequestCase("V1-VALID", "MOD-API-CONTRACT", "GET", "/v1/blocks", "valid headers", headers=V1_HEADERS, query={"page_size": 1}, mode="status"))
        self.assertLess(result.baseline.status or 999, 400)

    # TP-COMPATIBILITY-API-CONTRACT-006
    def test_tp_006_invalid_v1_content_type(self) -> None:
        self.assert_case(RequestCase("V1-BAD-CONTENT", "MOD-API-CONTRACT", "GET", "/v1/blocks", "bad content type", headers={"Accept": V1_HEADERS["Accept"], "Content-Type": "application/json"}), 415)

    # TP-COMPATIBILITY-API-CONTRACT-007
    def test_tp_007_invalid_v1_accept(self) -> None:
        self.assert_case(RequestCase("V1-BAD-ACCEPT", "MOD-API-CONTRACT", "GET", "/v1/blocks", "bad accept", headers={"Accept": "application/json", "Content-Type": V1_HEADERS["Content-Type"]}), 406)

    # TP-COMPATIBILITY-API-CONTRACT-008
    def test_tp_008_both_invalid_v1_headers_preserve_precedence(self) -> None:
        self.assert_case(RequestCase("V1-BOTH-BAD", "MOD-API-CONTRACT", "GET", "/v1/blocks", "both bad", headers={"Accept": "application/json", "Content-Type": "application/json"}), 415)
