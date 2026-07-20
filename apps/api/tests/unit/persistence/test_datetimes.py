from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from autoclaw.persistence.datetimes import UtcDateTime
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class _StampBase(DeclarativeBase):
    pass


class _StampModel(_StampBase):
    __tablename__ = "test_datetime_stamps"

    stamp_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stamped_at: Mapped[datetime] = mapped_column(UtcDateTime())


def test_sqlite_round_trip_returns_timezone_aware_utc() -> None:
    engine = create_engine("sqlite://")
    _StampBase.metadata.create_all(engine)
    written = datetime(2026, 7, 20, 9, 29, 52, 38802, tzinfo=UTC)

    with Session(engine) as session:
        session.add(_StampModel(stamp_id="aware-utc", stamped_at=written))
        session.commit()
    with Session(engine) as session:
        read = session.scalars(select(_StampModel.stamped_at)).one()

    assert read == written
    assert read.tzinfo == UTC


def test_non_utc_and_naive_writes_normalize_to_utc() -> None:
    engine = create_engine("sqlite://")
    _StampBase.metadata.create_all(engine)
    sydney = timezone(timedelta(hours=10))
    aware_local = datetime(2026, 7, 20, 19, 29, 52, tzinfo=sydney)
    naive_utc = datetime(2026, 7, 20, 9, 29, 52)

    with Session(engine) as session:
        session.add(_StampModel(stamp_id="aware-local", stamped_at=aware_local))
        session.add(_StampModel(stamp_id="naive-utc", stamped_at=naive_utc))
        session.commit()
    with Session(engine) as session:
        by_id = {row.stamp_id: row.stamped_at for row in session.scalars(select(_StampModel)).all()}

    assert by_id["aware-local"] == aware_local.astimezone(UTC)
    assert by_id["aware-local"].tzinfo == UTC
    assert by_id["naive-utc"] == naive_utc.replace(tzinfo=UTC)
