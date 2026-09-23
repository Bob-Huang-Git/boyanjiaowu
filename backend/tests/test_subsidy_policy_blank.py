from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.funding.allowances import half_day_amount, policy_thresholds


def error_code(exc: pytest.ExceptionInfo[HTTPException]) -> str:
    return exc.value.detail["code"]


def test_missing_attendance_thresholds_have_no_system_default() -> None:
    policy = SimpleNamespace(
        half_day_threshold_minutes=None,
        full_day_threshold_minutes=None,
    )

    with pytest.raises(HTTPException) as exc:
        policy_thresholds(policy)

    assert error_code(exc) == "ALLOWANCE_POLICY_THRESHOLDS_REQUIRED"


def test_missing_half_day_percentage_has_no_system_default() -> None:
    policy = SimpleNamespace(
        rule_params_json=None,
        rounding_rule="FLOOR",
        unit_amount_cent=1000,
    )

    with pytest.raises(HTTPException) as exc:
        half_day_amount(policy)

    assert error_code(exc) == "ALLOWANCE_POLICY_HALF_DAY_PERCENT_REQUIRED"
