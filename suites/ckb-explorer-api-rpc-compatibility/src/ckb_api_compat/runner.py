from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Iterable

from .compare import compare_observations
from .http import StdlibHttpClient
from .models import ComparisonResult, Observation, RequestCase


class PairedRunner:
    def __init__(
        self,
        baseline_url: str,
        candidate_url: str,
        *,
        client: StdlibHttpClient | None = None,
    ) -> None:
        self.baseline_url = baseline_url.rstrip("/")
        self.candidate_url = candidate_url.rstrip("/")
        self.client = client or StdlibHttpClient()
        if not self.baseline_url.startswith(("http://", "https://")):
            raise ValueError("baseline URL must use http:// or https://")
        if not self.candidate_url.startswith(("http://", "https://")):
            raise ValueError("candidate URL must use http:// or https://")

    @staticmethod
    def _empty(side: str, case: RequestCase) -> Observation:
        return Observation(side=side, method=case.method, url=case.path)  # type: ignore[arg-type]

    def run_case(self, case: RequestCase) -> ComparisonResult:
        request_id = str(uuid.uuid4())
        if not case.enabled:
            return ComparisonResult(
                request_id=request_id,
                case_id=case.id,
                matched=False,
                baseline=self._empty("baseline", case),
                candidate=self._empty("candidate", case),
                skipped=True,
                skip_reason=case.skip_reason or "case disabled",
            )
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ckb-api-compat") as executor:
            baseline_future = executor.submit(self.client.observe, "baseline", self.baseline_url, case)
            candidate_future = executor.submit(self.client.observe, "candidate", self.candidate_url, case)
            baseline = baseline_future.result()
            candidate = candidate_future.result()
        return compare_observations(request_id, case, baseline, candidate)

    def run(self, cases: Iterable[RequestCase], *, fail_fast: bool = False) -> list[ComparisonResult]:
        results: list[ComparisonResult] = []
        for case in cases:
            result = self.run_case(case)
            results.append(result)
            if fail_fast and not result.matched and not result.skipped:
                break
        return results
