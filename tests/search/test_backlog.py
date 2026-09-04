# coding=utf-8
"""Tests for the throttled backlog batch scheduler."""
from __future__ import unicode_literals

import datetime

from medusa import app
from medusa.search import backlog
from medusa.search.backlog import (
    BacklogSearcher,
    iter_wanted_segments,
    next_batch,
    parse_cursor,
    segment_key,
    serialize_cursor,
)

import pytest


class FakeSeries(object):
    """Minimal stand-in for a Series object as used by the backlog planner."""

    def __init__(self, indexer, series_id, seasons, paused=False):
        self.indexer = indexer
        self.series_id = series_id
        self.indexerid = series_id
        self.name = 'Show {0}-{1}'.format(indexer, series_id)
        self.paused = paused
        self.seasons = seasons
        self.wanted_calls = 0

    def get_wanted_segments(self, from_date=None):
        self.wanted_calls += 1
        return {season: ['ep-{0}-s{1}'.format(self.series_id, season)] for season in self.seasons}


class FakeQueueItem(object):
    """Replacement for BacklogQueueItem that avoids touching real Series/Episode objects."""

    def __init__(self, show, segment):
        self.show = show
        self.segment = segment


class FakeSearchQueue(object):
    """Search queue stub that reports a scripted number of pending backlog items."""

    def __init__(self, pending=None):
        self.items = []
        self.pending = list(pending or [])

    def add_item(self, item):
        self.items.append(item)

    def backlog_pending(self):
        if len(self.pending) > 1:
            return self.pending.pop(0)
        return self.pending[0] if self.pending else 0


class FakeScheduler(object):
    def __init__(self, action):
        self.action = action


@pytest.fixture
def library():
    # Deliberately unsorted to make sure the planner enforces its own order.
    return [
        FakeSeries(1, 30, seasons=[1]),
        FakeSeries(1, 10, seasons=[2, 1]),
        FakeSeries(1, 20, seasons=[], paused=False),
        FakeSeries(3, 5, seasons=[4]),
        FakeSeries(1, 15, seasons=[1], paused=True),
    ]


@pytest.fixture
def searcher(monkeypatch):
    monkeypatch.setattr(BacklogSearcher, '_get_last_backlog', lambda self: 1)
    # Bypass the BACKLOG_FREQUENCY property setter, which reconfigures the scheduler thread.
    monkeypatch.setattr(app, '_BACKLOG_FREQUENCY', 720)
    return BacklogSearcher()


@pytest.mark.parametrize('key,expected', [
    ((1, 10, 2), '1:10:2'),
    (None, ''),
    ((), ''),
])
def test_serialize_cursor(key, expected):
    assert serialize_cursor(key) == expected


@pytest.mark.parametrize('value,expected', [
    ('1:10:2', (1, 10, 2)),
    ('', None),
    (None, None),
    ('1:10', None),
    ('a:b:c', None),
])
def test_parse_cursor(value, expected):
    assert parse_cursor(value) == expected


def test_iter_wanted_segments_is_deterministic_and_skips_paused(library):
    keys = [key for _, _, _, key in iter_wanted_segments(library, datetime.date.fromordinal(1))]

    assert keys == [(1, 10, 1), (1, 10, 2), (1, 30, 1), (3, 5, 4)]


def test_iter_wanted_segments_resumes_after_cursor_without_querying_earlier_shows(library):
    keys = [key for _, _, _, key in iter_wanted_segments(library, datetime.date.fromordinal(1), cursor=(1, 20, 0))]

    assert keys == [(1, 30, 1), (3, 5, 4)]
    # Shows sorting strictly before the cursor must be skipped without a DB query.
    show_10 = next(series for series in library if series.series_id == 10)
    assert show_10.wanted_calls == 0
    # The show holding the cursor still has to be queried for later seasons.
    show_20 = next(series for series in library if series.series_id == 20)
    assert show_20.wanted_calls == 1


def test_iter_wanted_segments_resumes_mid_show(library):
    keys = [key for _, _, _, key in iter_wanted_segments(library, datetime.date.fromordinal(1), cursor=(1, 10, 1))]

    assert keys == [(1, 10, 2), (1, 30, 1), (3, 5, 4)]


def test_next_batch_limits_size_and_returns_empty_at_end(library):
    from_date = datetime.date.fromordinal(1)

    first = next_batch(library, from_date, None, 3)
    assert [key for _, _, _, key in first] == [(1, 10, 1), (1, 10, 2), (1, 30, 1)]

    second = next_batch(library, from_date, first[-1][3], 3)
    assert [key for _, _, _, key in second] == [(3, 5, 4)]

    assert next_batch(library, from_date, second[-1][3], 3) == []


def test_segment_key_coerces_to_int():
    assert segment_key(FakeSeries('1', '10', []), '3') == (1, 10, 3)


def test_search_in_batches_walks_whole_library_and_clears_cursor(monkeypatch, searcher, library):
    queue = FakeSearchQueue(pending=[0])
    cursors = []

    monkeypatch.setattr(app, 'search_queue_scheduler', FakeScheduler(queue))
    monkeypatch.setattr(app, 'backlog_search_scheduler', None)
    monkeypatch.setattr(app, 'BACKLOG_BATCH_SIZE', 3)
    monkeypatch.setattr(app, 'BACKLOG_BATCH_REFILL_THRESHOLD', 0)
    monkeypatch.setattr(backlog, 'BacklogQueueItem', FakeQueueItem)
    monkeypatch.setattr(searcher, '_get_cursor', lambda: None)
    monkeypatch.setattr(searcher, '_set_cursor', cursors.append)

    completed = searcher._search_in_batches(library, datetime.date.fromordinal(1), resume=True)

    assert completed is True
    assert [item.show.series_id for item in queue.items] == [10, 10, 30, 5]
    assert cursors == [(1, 30, 1), (3, 5, 4), None]


def test_search_in_batches_resumes_from_persisted_cursor(monkeypatch, searcher, library):
    queue = FakeSearchQueue(pending=[0])

    monkeypatch.setattr(app, 'search_queue_scheduler', FakeScheduler(queue))
    monkeypatch.setattr(app, 'backlog_search_scheduler', None)
    monkeypatch.setattr(app, 'BACKLOG_BATCH_SIZE', 10)
    monkeypatch.setattr(app, 'BACKLOG_BATCH_REFILL_THRESHOLD', 2)
    monkeypatch.setattr(backlog, 'BacklogQueueItem', FakeQueueItem)
    monkeypatch.setattr(searcher, '_get_cursor', lambda: (1, 10, 2))
    monkeypatch.setattr(searcher, '_set_cursor', lambda key: None)

    assert searcher._search_in_batches(library, datetime.date.fromordinal(1), resume=True) is True
    assert [item.show.series_id for item in queue.items] == [30, 5]


def test_search_in_batches_without_resume_ignores_cursor(monkeypatch, searcher, library):
    queue = FakeSearchQueue(pending=[0])
    cursors = []

    monkeypatch.setattr(app, 'search_queue_scheduler', FakeScheduler(queue))
    monkeypatch.setattr(app, 'backlog_search_scheduler', None)
    monkeypatch.setattr(app, 'BACKLOG_BATCH_SIZE', 10)
    monkeypatch.setattr(app, 'BACKLOG_BATCH_REFILL_THRESHOLD', 2)
    monkeypatch.setattr(backlog, 'BacklogQueueItem', FakeQueueItem)
    monkeypatch.setattr(searcher, '_get_cursor', lambda: (1, 10, 2))
    monkeypatch.setattr(searcher, '_set_cursor', cursors.append)

    assert searcher._search_in_batches(library, datetime.date.fromordinal(1), resume=False) is True
    assert len(queue.items) == 4
    assert cursors == []


def test_search_in_batches_waits_for_capacity_before_next_batch(monkeypatch, searcher, library):
    # First call: queue empty. Second call: still busy, then drained. Third: empty again.
    queue = FakeSearchQueue(pending=[0, 5, 1, 0])
    waits = []

    monkeypatch.setattr(app, 'search_queue_scheduler', FakeScheduler(queue))
    monkeypatch.setattr(app, 'backlog_search_scheduler', None)
    monkeypatch.setattr(app, 'BACKLOG_BATCH_SIZE', 3)
    monkeypatch.setattr(app, 'BACKLOG_BATCH_REFILL_THRESHOLD', 1)
    monkeypatch.setattr(backlog, 'BacklogQueueItem', FakeQueueItem)
    monkeypatch.setattr(searcher, '_get_cursor', lambda: None)
    monkeypatch.setattr(searcher, '_set_cursor', lambda key: None)
    monkeypatch.setattr(searcher._capacity, 'wait', lambda timeout=None: waits.append(timeout))

    assert searcher._search_in_batches(library, datetime.date.fromordinal(1), resume=True) is True
    assert len(queue.items) == 4
    # Exactly one wait happened: while 5 searches were pending above the threshold of 1.
    assert waits == [backlog.CAPACITY_WAIT_FALLBACK_SECONDS]


def test_search_in_batches_stops_on_shutdown_and_keeps_cursor(monkeypatch, searcher, library):
    queue = FakeSearchQueue(pending=[0, 5])
    cursors = []
    scheduler = FakeScheduler(searcher)

    class StopEvent(object):
        def __init__(self):
            self.checks = 0

        def is_set(self):
            # Allow the first batch, then request shutdown while waiting on the second.
            self.checks += 1
            return self.checks > 1

    scheduler.stop = StopEvent()

    monkeypatch.setattr(app, 'search_queue_scheduler', FakeScheduler(queue))
    monkeypatch.setattr(app, 'backlog_search_scheduler', scheduler)
    monkeypatch.setattr(app, 'BACKLOG_BATCH_SIZE', 3)
    monkeypatch.setattr(app, 'BACKLOG_BATCH_REFILL_THRESHOLD', 0)
    monkeypatch.setattr(backlog, 'BacklogQueueItem', FakeQueueItem)
    monkeypatch.setattr(searcher, '_get_cursor', lambda: None)
    monkeypatch.setattr(searcher, '_set_cursor', cursors.append)

    assert searcher._search_in_batches(library, datetime.date.fromordinal(1), resume=True) is False
    assert len(queue.items) == 3
    assert cursors == [(1, 30, 1)]


def test_search_backlog_uses_legacy_path_when_batching_disabled(monkeypatch, searcher, library):
    queue = FakeSearchQueue()
    calls = []

    monkeypatch.setattr(app, 'showList', library)
    monkeypatch.setattr(app, 'search_queue_scheduler', FakeScheduler(queue))
    monkeypatch.setattr(app, 'forced_search_queue_scheduler',
                        FakeScheduler(type('Forced', (object,), {'is_forced_search_in_progress': lambda self: False})()))
    monkeypatch.setattr(app, 'BACKLOG_BATCH_SIZE', 0)
    monkeypatch.setattr(backlog, 'BacklogQueueItem', FakeQueueItem)
    monkeypatch.setattr(searcher, '_get_last_backlog', lambda: 1)
    monkeypatch.setattr(searcher, '_set_last_backlog', calls.append)
    monkeypatch.setattr(searcher, '_search_in_batches',
                        lambda *args, **kwargs: pytest.fail('batched path must not run when disabled'))

    searcher.search_backlog()

    assert len(queue.items) == 4
    assert calls == [datetime.date.today().toordinal()]
    assert searcher.amActive is False


def test_search_backlog_targeted_shows_bypass_batching(monkeypatch, searcher, library):
    queue = FakeSearchQueue()
    calls = []

    monkeypatch.setattr(app, 'search_queue_scheduler', FakeScheduler(queue))
    monkeypatch.setattr(app, 'forced_search_queue_scheduler',
                        FakeScheduler(type('Forced', (object,), {'is_forced_search_in_progress': lambda self: False})()))
    monkeypatch.setattr(app, 'BACKLOG_BATCH_SIZE', 2)
    monkeypatch.setattr(backlog, 'BacklogQueueItem', FakeQueueItem)
    monkeypatch.setattr(searcher, '_get_last_backlog', lambda: 1)
    monkeypatch.setattr(searcher, '_set_last_backlog', calls.append)
    monkeypatch.setattr(searcher, '_search_in_batches',
                        lambda *args, **kwargs: pytest.fail('targeted backlog must stay immediate'))

    searcher.search_backlog(which_shows=[library[0]])

    assert [item.show.series_id for item in queue.items] == [30]
    # A targeted run is not a full backlog pass.
    assert calls == []


def test_search_backlog_interrupted_pass_does_not_record_last_backlog(monkeypatch, searcher, library):
    calls = []

    monkeypatch.setattr(app, 'showList', library)
    monkeypatch.setattr(app, 'forced_search_queue_scheduler',
                        FakeScheduler(type('Forced', (object,), {'is_forced_search_in_progress': lambda self: False})()))
    monkeypatch.setattr(app, 'BACKLOG_BATCH_SIZE', 2)
    monkeypatch.setattr(searcher, '_get_last_backlog', lambda: 1)
    monkeypatch.setattr(searcher, '_set_last_backlog', calls.append)
    monkeypatch.setattr(searcher, '_search_in_batches', lambda *args, **kwargs: False)

    searcher.search_backlog()

    assert calls == []
    assert searcher.amActive is False
