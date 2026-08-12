from ckb_api_compat.models import RequestCase
from tests.contract_support import LiveContractTestCase, V1_HEADERS


class RepresentationContractTests(LiveContractTestCase):
    # TP-COMPATIBILITY-API-CONTRACT-009
    def test_tp_009_v1_collection_json_api_representation(self) -> None:
        self.assert_case(RequestCase("V1-COLLECTION", "MOD-API-CONTRACT", "GET", "/v1/blocks", "V1 collection", headers=V1_HEADERS, query={"page": 1, "page_size": 2}))

    # TP-COMPATIBILITY-API-CONTRACT-010
    def test_tp_010_v1_exception_envelope(self) -> None:
        result = self.assert_case(RequestCase("V1-ERROR", "MOD-API-CONTRACT", "GET", "/v1/blocks/__compat_missing__", "V1 missing", headers=V1_HEADERS))
        self.assertGreaterEqual(result.baseline.status or 0, 400)

    # TP-COMPATIBILITY-API-CONTRACT-011
    def test_tp_011_v1_malformed_and_absent_identifiers(self) -> None:
        malformed = self.assert_case(RequestCase("V1-MALFORMED", "MOD-API-CONTRACT", "GET", "/v1/blocks/not-a-height-or-hash", "malformed", headers=V1_HEADERS))
        absent = self.assert_case(RequestCase("V1-ABSENT", "MOD-API-CONTRACT", "GET", "/v1/blocks/999999999999999999", "absent", headers=V1_HEADERS))
        self.assertGreaterEqual(malformed.baseline.status or 0, 400)
        self.assertGreaterEqual(absent.baseline.status or 0, 400)

    # TP-COMPATIBILITY-API-CONTRACT-012
    def test_tp_012_v1_scalar_types_and_values(self) -> None:
        self.assert_case(RequestCase("V1-TYPES", "MOD-API-CONTRACT", "GET", "/v1/statistics", "types", headers=V1_HEADERS))

    # TP-COMPATIBILITY-API-CONTRACT-013
    def test_tp_013_v2_collection_representation(self) -> None:
        self.assert_case(RequestCase("V2-COLLECTION", "MOD-API-CONTRACT", "GET", "/v2/fiber/graph_nodes", "V2 collection", query={"page": 1, "page_size": 2}))

    # TP-COMPATIBILITY-API-CONTRACT-014
    def test_tp_014_v2_parameter_failure(self) -> None:
        result = self.assert_case(RequestCase("V2-PARAMS", "MOD-API-CONTRACT", "GET", "/v2/fiber/graph_nodes", "V2 parameter error", query={"page": "bad"}))
        self.assertGreaterEqual(result.baseline.status or 0, 400)

    # TP-COMPATIBILITY-API-CONTRACT-015
    def test_tp_015_v2_authentication_error(self) -> None:
        result = self.assert_case(RequestCase("V2-AUTH", "MOD-API-CONTRACT", "GET", "/v2/portfolio/user", "V2 auth error"))
        self.assertGreaterEqual(result.baseline.status or 0, 400)

    # TP-COMPATIBILITY-API-CONTRACT-016
    def test_tp_016_v2_absent_identifier(self) -> None:
        result = self.assert_case(RequestCase("V2-ABSENT", "MOD-API-CONTRACT", "GET", "/v2/fiber/graph_nodes/__compat_missing__", "V2 absent"))
        self.assertGreaterEqual(result.baseline.status or 0, 400)
