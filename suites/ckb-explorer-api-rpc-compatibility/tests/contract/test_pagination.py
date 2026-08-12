from ckb_api_compat.models import RequestCase
from tests.contract_support import LiveContractTestCase, V1_HEADERS


class PaginationContractTests(LiveContractTestCase):
    # TP-COMPATIBILITY-API-CONTRACT-017
    def test_tp_017_default_pagination(self) -> None:
        self.assert_case(RequestCase("PAGE-DEFAULT", "MOD-API-CONTRACT", "GET", "/v1/blocks", "default page", headers=V1_HEADERS))

    # TP-COMPATIBILITY-API-CONTRACT-018
    def test_tp_018_adjacent_pages(self) -> None:
        for page in (1, 2):
            self.assert_case(RequestCase(f"PAGE-{page}", "MOD-API-CONTRACT", "GET", "/v1/blocks", "adjacent page", headers=V1_HEADERS, query={"page": page, "page_size": 2}))

    # TP-COMPATIBILITY-API-CONTRACT-019
    def test_tp_019_invalid_v1_pagination(self) -> None:
        for name, value in (("text", "bad"), ("zero", 0), ("negative", -1)):
            result = self.assert_case(RequestCase(f"PAGE-{name}", "MOD-API-CONTRACT", "GET", "/v1/blocks", "invalid page", headers=V1_HEADERS, query={"page": value}))
            self.assertEqual(400, result.baseline.status)

    # TP-COMPATIBILITY-API-CONTRACT-020
    def test_tp_020_out_of_range_page(self) -> None:
        self.assert_case(RequestCase("PAGE-EMPTY", "MOD-API-CONTRACT", "GET", "/v1/blocks", "empty page", headers=V1_HEADERS, query={"page": 999999999, "page_size": 2}))

    # TP-COMPATIBILITY-API-CONTRACT-021
    def test_tp_021_repeated_supported_sort(self) -> None:
        case = RequestCase("SORT-VALID", "MOD-API-CONTRACT", "GET", "/v1/blocks", "sort", headers=V1_HEADERS, query={"sort": "block_number.desc", "page_size": 2})
        self.assert_case(case)
        self.assert_case(case)

    # TP-COMPATIBILITY-API-CONTRACT-022
    def test_tp_022_unsupported_sort_and_oversized_page(self) -> None:
        self.assert_case(RequestCase("SORT-BAD", "MOD-API-CONTRACT", "GET", "/v1/blocks", "bad sort", headers=V1_HEADERS, query={"sort": "__bad__.sideways", "page_size": 999999}))
