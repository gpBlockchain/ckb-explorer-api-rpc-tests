from ckb_api_compat.models import RequestCase
from tests.contract_support import LiveContractTestCase, V1_HEADERS


class RoutingContractTests(LiveContractTestCase):
    # TP-COMPATIBILITY-API-CONTRACT-004
    def test_tp_004_unknown_path_and_wrong_method(self) -> None:
        self.assert_case(RequestCase("UNKNOWN", "MOD-API-CONTRACT", "GET", "/v1/__compat_unknown__", "unknown", headers=V1_HEADERS))
        self.assert_case(RequestCase("WRONG-METHOD", "MOD-API-CONTRACT", "OPTIONS", "/v1/blocks", "wrong method", headers=V1_HEADERS))
