import unittest

from ckb_api_compat.models import RequestCase
from tests.contract_support import LiveContractTestCase, RUN_EXPORTS, V1_HEADERS


@unittest.skipUnless(RUN_EXPORTS, "set RUN_LIVE_EXPORTS=1 for CSV endpoints")
class CsvContractTests(LiveContractTestCase):
    # TP-COMPATIBILITY-API-CONTRACT-023
    def test_tp_023_csv_transport_metadata(self) -> None:
        self.assert_case(RequestCase("CSV-TRANSPORT", "MOD-API-CONTRACT", "GET", "/v1/blocks/download_csv", "CSV transport", headers=V1_HEADERS, mode="csv"))

    # TP-COMPATIBILITY-API-CONTRACT-024
    def test_tp_024_csv_rows_and_order(self) -> None:
        self.assert_case(RequestCase("CSV-ROWS", "MOD-API-CONTRACT", "GET", "/v1/blocks/download_csv", "CSV rows", headers=V1_HEADERS, mode="csv"))

    # TP-COMPATIBILITY-API-CONTRACT-025
    def test_tp_025_csv_empty_and_boundary_range(self) -> None:
        self.assert_case(RequestCase("CSV-EMPTY", "MOD-API-CONTRACT", "GET", "/v1/blocks/download_csv", "CSV empty", headers=V1_HEADERS, query={"start_date": "2999-01-01", "end_date": "2999-01-02"}, mode="csv"))

    # TP-COMPATIBILITY-API-CONTRACT-026
    def test_tp_026_csv_encoding_and_quoting_fixture(self) -> None:
        self.assert_case(RequestCase("CSV-ENCODING", "MOD-API-CONTRACT", "GET", "/v1/blocks/download_csv", "CSV encoding", headers=V1_HEADERS, mode="csv"))
