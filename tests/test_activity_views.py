from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from omarchy_garmin.activities import Activity
from omarchy_garmin.activity_views import (
    MAX_ACTIVITY_PAGE_OFFSET,
    MAX_ACTIVITY_PAGE_SIZE,
    ActivityViewDataError,
    ActivityViewRequestError,
    ActivityViewService,
    ActivityViewStorageError,
    activity_detail_payload,
    activity_page_payload,
)
from omarchy_garmin.database import ActivityDatabaseError

_AS_OF = date(2026, 8, 26)


def _activity(activity_id: str, *, name: str | None = "Fabricated ride") -> Activity:
    return Activity(
        activity_id=activity_id,
        name=name,
        type_key="synthetic_cycling",
        started_at_local="2026-08-25 18:30:00",
        local_date=date(2026, 8, 25),
        duration_seconds=3600,
        moving_duration_seconds=3500,
        distance_metres=25_000,
        elevation_gain_metres=300,
        energy_joules=2_000_000,
        average_heart_rate_bpm=140,
        maximum_heart_rate_bpm=175,
        average_speed_metres_per_second=7.1,
        average_power_watts=190,
        total_sets=None,
        total_repetitions=None,
    )


class _FakeRepository:
    def __init__(
        self,
        activities: list[Activity] | None = None,
        *,
        detail: Activity | None = None,
        failure: ActivityDatabaseError | None = None,
    ) -> None:
        self.activities = activities or []
        self.detail = detail
        self.failure = failure
        self.page_calls: list[tuple[date, date, str | None, int, int]] = []
        self.detail_calls: list[str] = []

    def activity_page(
        self,
        start_date: date,
        end_date: date,
        *,
        type_key: str | None,
        offset: int,
        limit: int,
    ) -> list[Activity]:
        self.page_calls.append((start_date, end_date, type_key, offset, limit))
        if self.failure is not None:
            raise self.failure
        return self.activities[:limit]

    def activity_by_id(self, activity_id: str) -> Activity | None:
        self.detail_calls.append(activity_id)
        if self.failure is not None:
            raise self.failure
        return self.detail


def test_activity_page_uses_calendar_period_filter_and_fixed_limit() -> None:
    repository = _FakeRepository([_activity(str(index)) for index in range(21, 0, -1)])
    service = ActivityViewService(repository, today=lambda: _AS_OF)

    page = service.list_activities(
        period_key="7Days",
        as_of_date=_AS_OF,
        type_key="synthetic_cycling",
        offset=0,
    )

    assert repository.page_calls == [(date(2026, 8, 20), _AS_OF, "synthetic_cycling", 0, 21)]
    assert len(page.activities) == MAX_ACTIVITY_PAGE_SIZE
    assert page.has_more is True
    assert page.next_offset == 20
    assert page.stale is False


def test_old_activity_page_is_marked_stale_without_network_access() -> None:
    repository = _FakeRepository()
    service = ActivityViewService(repository, today=lambda: date(2026, 8, 27))

    page = service.list_activities(
        period_key="today",
        as_of_date=_AS_OF,
        type_key=None,
        offset=0,
    )

    assert page.stale is True
    assert page.activities == ()
    assert page.has_more is False
    assert page.next_offset is None


def test_activity_page_payload_contains_only_bounded_list_fields() -> None:
    service = ActivityViewService(_FakeRepository([_activity("101")]), today=lambda: _AS_OF)

    payload = activity_page_payload(
        service.list_activities(
            period_key="30Days",
            as_of_date=_AS_OF,
            type_key=None,
            offset=0,
        )
    )

    assert payload["pageSize"] == 20
    assert payload["activities"] == [
        {
            "activityId": "101",
            "name": "Fabricated ride",
            "typeKey": "synthetic_cycling",
            "startedAtLocal": "2026-08-25 18:30:00",
            "localDate": "2026-08-25",
            "durationSeconds": 3600,
            "distanceMetres": 25_000,
            "energyJoules": 2_000_000,
            "totalSets": None,
            "totalRepetitions": None,
        }
    ]
    assert "url" not in str(payload).lower()
    assert "latitude" not in str(payload).lower()


def test_activity_detail_payload_preserves_nulls_and_all_reviewed_metrics() -> None:
    activity = _activity("101", name=None)
    detail = ActivityViewService(
        _FakeRepository(detail=activity), today=lambda: _AS_OF
    ).activity_detail("101")

    payload = activity_detail_payload(detail)

    assert payload["found"] is True
    assert payload["activity"] == {
        "activityId": "101",
        "name": None,
        "typeKey": "synthetic_cycling",
        "startedAtLocal": "2026-08-25 18:30:00",
        "localDate": "2026-08-25",
        "durationSeconds": 3600,
        "movingDurationSeconds": 3500,
        "distanceMetres": 25_000,
        "elevationGainMetres": 300,
        "energyJoules": 2_000_000,
        "averageHeartRateBpm": 140,
        "maximumHeartRateBpm": 175,
        "averageSpeedMetresPerSecond": 7.1,
        "averagePowerWatts": 190,
        "totalSets": None,
        "totalRepetitions": None,
    }


def test_activity_detail_rejects_repository_row_for_a_different_identifier() -> None:
    repository = _FakeRepository(detail=_activity("102"))

    with pytest.raises(ActivityViewDataError, match="unexpected identifier"):
        ActivityViewService(repository, today=lambda: _AS_OF).activity_detail("101")


def test_missing_activity_detail_returns_stable_not_found_result() -> None:
    repository = _FakeRepository(detail=None)

    detail = ActivityViewService(repository, today=lambda: _AS_OF).activity_detail("101")

    assert repository.detail_calls == ["101"]
    assert activity_detail_payload(detail) == {"found": False, "activity": None}


@pytest.mark.parametrize(
    "activity_id",
    [
        pytest.param("", id="empty"),
        pytest.param("0", id="zero"),
        pytest.param("01", id="leading-zero"),
        pytest.param("1 OR 1=1", id="sql-injection"),
        pytest.param("9223372036854775808", id="above-signed-64-bit"),
        pytest.param("\uff11\uff12\uff13", id="non-ascii-digits"),
    ],
)
def test_invalid_activity_identifier_is_rejected_before_repository_read(
    activity_id: str,
) -> None:
    repository = _FakeRepository()

    with pytest.raises(ActivityViewRequestError):
        ActivityViewService(repository, today=lambda: _AS_OF).activity_detail(activity_id)

    assert repository.detail_calls == []


@pytest.mark.parametrize(
    ("period", "as_of", "type_key", "offset"),
    [
        pytest.param("year", _AS_OF, None, 0, id="unknown-period"),
        pytest.param("7Days", date(2026, 8, 27), None, 0, id="future-date"),
        pytest.param(
            "7Days",
            datetime(2026, 8, 26, 12, tzinfo=UTC),
            None,
            0,
            id="datetime-as-local-date",
        ),
        pytest.param("7Days", _AS_OF, "", 0, id="empty-type"),
        pytest.param("7Days", _AS_OF, "run\nning", 0, id="control-character"),
        pytest.param("7Days", _AS_OF, None, 1, id="unaligned-offset"),
        pytest.param(
            "7Days",
            _AS_OF,
            None,
            MAX_ACTIVITY_PAGE_OFFSET + MAX_ACTIVITY_PAGE_SIZE,
            id="offset-too-large",
        ),
    ],
)
def test_invalid_page_request_is_rejected_before_repository_read(
    period: str,
    as_of: date,
    type_key: str | None,
    offset: int,
) -> None:
    repository = _FakeRepository()

    with pytest.raises(ActivityViewRequestError):
        ActivityViewService(repository, today=lambda: _AS_OF).list_activities(
            period_key=period,
            as_of_date=as_of,
            type_key=type_key,
            offset=offset,
        )

    assert repository.page_calls == []


@pytest.mark.parametrize(
    ("activities", "type_key"),
    [
        pytest.param(
            [
                replace(
                    _activity("101"),
                    local_date=date(2026, 8, 19),
                    started_at_local="2026-08-19 18:30:00",
                )
            ],
            None,
            id="outside-period",
        ),
        pytest.param([_activity("101")], "running", id="wrong-filtered-type"),
        pytest.param([_activity("101"), _activity("101")], None, id="duplicate-id"),
        pytest.param([_activity("1"), _activity("2")], None, id="not-newest-first"),
    ],
)
def test_inconsistent_stored_activity_page_is_rejected(
    activities: list[Activity],
    type_key: str | None,
) -> None:
    repository = _FakeRepository(activities)

    with pytest.raises(ActivityViewDataError, match="stored activity page"):
        ActivityViewService(repository, today=lambda: _AS_OF).list_activities(
            period_key="7Days",
            as_of_date=_AS_OF,
            type_key=type_key,
            offset=0,
        )


def test_malformed_stored_activity_is_rejected_from_view_contract() -> None:
    malformed = _activity("101", name="hostile\nname")
    repository = _FakeRepository([malformed])

    with pytest.raises(ActivityViewDataError, match="stored activity"):
        ActivityViewService(repository, today=lambda: _AS_OF).list_activities(
            period_key="7Days",
            as_of_date=_AS_OF,
            type_key=None,
            offset=0,
        )


def test_database_failure_is_mapped_to_safe_view_storage_error() -> None:
    repository = _FakeRepository(failure=ActivityDatabaseError("private SQL detail"))

    with pytest.raises(ActivityViewStorageError, match="unavailable"):
        ActivityViewService(repository, today=lambda: _AS_OF).activity_detail("101")
