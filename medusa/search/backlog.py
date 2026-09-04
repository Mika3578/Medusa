# coding=utf-8

"""Backlog module."""
from __future__ import unicode_literals

import datetime
import logging
import threading
from builtins import object
from builtins import str
from itertools import islice
from uuid import uuid4

from medusa import app, db, ui, ws
from medusa.logger.adapters.style import BraceAdapter
from medusa.schedulers import scheduler
from medusa.search.queue import BacklogQueueItem

from six import iteritems

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())

# Upper bound on how long the batch loop sleeps when no completion
# notification arrives. Completions wake the loop immediately; this only
# guards against a missed notification.
CAPACITY_WAIT_FALLBACK_SECONDS = 30

CURSOR_SEPARATOR = ':'


def segment_key(series_obj, season):
    """Return the deterministic ordering key of a backlog season segment."""
    return (int(series_obj.indexer), int(series_obj.series_id), int(season))


def serialize_cursor(key):
    """Serialize a segment key into its persisted string form."""
    if not key:
        return ''
    return CURSOR_SEPARATOR.join(str(part) for part in key)


def parse_cursor(value):
    """Parse a persisted cursor. Return ``None`` when it is empty or malformed."""
    if not value:
        return None
    parts = str(value).split(CURSOR_SEPARATOR)
    if len(parts) != 3:
        return None
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def iter_wanted_segments(show_list, from_date, cursor=None):
    """Yield wanted season segments in a stable order, resuming after ``cursor``.

    Shows are visited sorted by ``(indexer, series_id)`` and seasons ascending,
    so the same library always yields the same sequence. Shows that sort before
    the cursor are skipped without hitting the database.

    :yield: ``(series_obj, season, episodes, key)`` tuples.
    """
    for series_obj in sorted(show_list, key=lambda series: (int(series.indexer), int(series.series_id))):
        if series_obj.paused:
            continue

        if cursor and (int(series_obj.indexer), int(series_obj.series_id)) < cursor[:2]:
            continue

        segments = series_obj.get_wanted_segments(from_date=from_date)
        if not segments:
            log.debug(u'Nothing needs to be downloaded for {0!r}, skipping', series_obj.name)
            continue

        for season in sorted(segments):
            key = segment_key(series_obj, season)
            if cursor and key <= cursor:
                continue
            yield series_obj, season, segments[season], key


def next_batch(show_list, from_date, cursor, size):
    """Return up to ``size`` wanted segments following ``cursor``."""
    return list(islice(iter_wanted_segments(show_list, from_date, cursor), size))


class BacklogSearchScheduler(scheduler.Scheduler):
    """Backlog search scheduler class."""

    def force_search(self):
        """Set the last backlog in the DB."""
        self.action._set_last_backlog(1)
        self.lastRun = datetime.datetime.fromordinal(1)

    def next_run(self):
        """Return when backlog should run next."""
        if self.action._last_backlog <= 1:
            return datetime.date.today()
        else:
            backlog_frequency_in_days = int(self.action.cycleTime)
            return datetime.date.fromordinal(self.action._last_backlog + backlog_frequency_in_days)


class BacklogSearcher(object):
    """Backlog Searcher class."""

    def __init__(self):
        """Initialize the class."""
        self._last_backlog = self._get_last_backlog()
        self.cycleTime = app.BACKLOG_FREQUENCY / 60.0 / 24
        self.lock = threading.Lock()
        self.amActive = False
        self.amPaused = False
        self.amWaiting = False
        self.forced = False
        self.currentSearchInfo = {}
        self._capacity = threading.Event()

        self._to_json = {
            'identifier': str(uuid4()),
            'name': 'BACKLOG',
            'queueTime': str(datetime.datetime.utcnow()),
            'force': self.forced
        }

        self._reset_pi()

    def _reset_pi(self):
        """Reset percent done."""
        self.percentDone = 0
        self.currentSearchInfo = {'title': 'Initializing'}

    def get_progress_indicator(self):
        """Get backlog search progress indicator."""
        if self.amActive:
            return ui.ProgressIndicator(self.percentDone, self.currentSearchInfo)
        else:
            return None

    def am_running(self):
        """Check if backlog is running."""
        log.debug(u'amWaiting: {0}, amActive: {1}', self.amWaiting, self.amActive)
        return (not self.amWaiting) and self.amActive

    def notify_capacity(self):
        """Wake the batch loop because a backlog search finished."""
        self._capacity.set()

    def search_backlog(self, which_shows=None):
        """Run the backlog search for given shows."""
        if self.amActive:
            log.debug(u'Backlog is still running, not starting it again')
            return

        if app.forced_search_queue_scheduler.action.is_forced_search_in_progress():
            log.warning(u'Manual search is running. Unable to start Backlog Search')
            return

        self.amActive = True
        self.amPaused = False

        if which_shows:
            show_list = which_shows
        else:
            show_list = app.showList

        self._get_last_backlog()

        cur_date = datetime.date.today().toordinal()
        from_date = datetime.date.fromordinal(1)
        limited = not which_shows and self.forced

        if limited:
            log.info(u'Running limited backlog search on missed episodes from last {0} days',
                     app.BACKLOG_DAYS)
            from_date = datetime.date.today() - datetime.timedelta(days=app.BACKLOG_DAYS)
        else:
            log.info(u'Running full backlog search on missed episodes for selected shows')

        try:
            if which_shows or app.BACKLOG_BATCH_SIZE <= 0:
                completed = self._search_all(show_list, from_date)
            else:
                # Only a full library pass keeps a persistent position; a limited
                # (forced) pass always starts from the beginning.
                completed = self._search_in_batches(show_list, from_date, resume=not limited)
        finally:
            self.amActive = False
            self._reset_pi()

        # don't consider this an actual backlog search if we only did recent eps
        # or if we only did certain shows, or if the pass was interrupted
        if completed and from_date == datetime.date.fromordinal(1) and not which_shows:
            self._set_last_backlog(cur_date)

    def _search_all(self, show_list, from_date):
        """Queue every wanted segment at once (legacy, unthrottled behavior)."""
        # go through non air-by-date shows and see if they need any episodes
        for series_obj in show_list:

            if series_obj.paused:
                continue

            segments = series_obj.get_wanted_segments(from_date=from_date)

            for season, segment in iteritems(segments):
                self.currentSearchInfo = {'title': '{series_name} Season {season}'.format(series_name=series_obj.name,
                                                                                          season=season)}

                backlog_queue_item = BacklogQueueItem(series_obj, segment)
                app.search_queue_scheduler.action.add_item(backlog_queue_item)  # @UndefinedVariable

            if not segments:
                log.debug(u'Nothing needs to be downloaded for {0!r}, skipping', series_obj.name)

        return True

    def _search_in_batches(self, show_list, from_date, resume):
        """Queue wanted segments in bounded batches, refilling as searches complete.

        Each batch is queued only once the number of pending backlog searches
        has dropped to the configured threshold, so a large library never floods
        the search queue and slow providers are not hammered. The position is
        persisted after every batch so an interrupted pass resumes where it
        stopped.

        :return: ``True`` when the whole pass completed, ``False`` when interrupted.
        """
        batch_size = int(app.BACKLOG_BATCH_SIZE)
        threshold = max(0, int(app.BACKLOG_BATCH_REFILL_THRESHOLD))
        cursor = self._get_cursor() if resume else None

        if cursor:
            log.info(u'Resuming backlog search from cursor {0}', serialize_cursor(cursor))

        while True:
            if not self._wait_for_capacity(threshold):
                log.info(u'Backlog search interrupted, it will resume from cursor {0}',
                         serialize_cursor(cursor))
                return False

            batch = next_batch(show_list, from_date, cursor, batch_size)
            if not batch:
                break

            for series_obj, season, segment, key in batch:
                self.currentSearchInfo = {'title': '{series_name} Season {season}'.format(series_name=series_obj.name,
                                                                                          season=season)}

                backlog_queue_item = BacklogQueueItem(series_obj, segment)
                app.search_queue_scheduler.action.add_item(backlog_queue_item)  # @UndefinedVariable
                cursor = key

            if resume:
                self._set_cursor(cursor)

            log.info(u'Queued a backlog batch of {0} season segment(s), waiting for the search queue to drain',
                     len(batch))

        if resume:
            self._set_cursor(None)

        return True

    def _wait_for_capacity(self, threshold):
        """Block until pending backlog searches drop to ``threshold``.

        :return: ``False`` when the application is shutting down.
        """
        while not self._should_stop():
            # Clear before counting so a completion that lands in between is
            # not lost and wakes the wait immediately.
            self._capacity.clear()

            pending = app.search_queue_scheduler.action.backlog_pending()
            if pending <= threshold:
                return True

            log.debug(u'{0} backlog search(es) pending, waiting for capacity (threshold: {1})', pending, threshold)
            self._capacity.wait(CAPACITY_WAIT_FALLBACK_SECONDS)

        return False

    @staticmethod
    def _should_stop():
        """Check whether the backlog scheduler thread was asked to stop."""
        backlog_scheduler = app.backlog_search_scheduler
        return backlog_scheduler is not None and backlog_scheduler.stop.is_set()

    def _get_last_backlog(self):
        """Get the last time backloged runned."""
        log.debug(u'Retrieving the last check time from the DB')

        main_db_con = db.DBConnection()
        sql_results = main_db_con.select('SELECT last_backlog '
                                         'FROM info')

        if not sql_results:
            last_backlog = 1
        elif sql_results[0]['last_backlog'] is None or sql_results[0]['last_backlog'] == '':
            last_backlog = 1
        else:
            last_backlog = int(sql_results[0]['last_backlog'])
            if last_backlog > datetime.date.today().toordinal():
                last_backlog = 1

        self._last_backlog = last_backlog
        return self._last_backlog

    @staticmethod
    def _set_last_backlog(when):
        """Set the last backlog in the DB."""
        log.debug(u'Setting the last backlog in the DB to {0}', when)

        main_db_con = db.DBConnection()
        sql_results = main_db_con.select('SELECT last_backlog '
                                         'FROM info')

        if not sql_results:
            main_db_con.action('INSERT INTO info (last_backlog, last_indexer) '
                               'VALUES (?,?)', [str(when), 0])
        else:
            main_db_con.action('UPDATE info '
                               'SET last_backlog={0}'.format(when))

    @staticmethod
    def _get_cursor():
        """Get the persisted backlog batch cursor from the DB."""
        main_db_con = db.DBConnection()
        sql_results = main_db_con.select('SELECT backlog_cursor FROM info')

        if not sql_results:
            return None

        return parse_cursor(sql_results[0]['backlog_cursor'])

    @staticmethod
    def _set_cursor(key):
        """Persist the backlog batch cursor in the DB. ``None`` clears it."""
        value = serialize_cursor(key)
        log.debug(u'Setting the backlog cursor in the DB to {0!r}', value)

        main_db_con = db.DBConnection()
        sql_results = main_db_con.select('SELECT backlog_cursor FROM info')

        if not sql_results:
            main_db_con.action('INSERT INTO info (last_backlog, last_indexer, backlog_cursor) '
                               'VALUES (?,?,?)', [0, 0, value])
        else:
            main_db_con.action('UPDATE info SET backlog_cursor = ?', [value])

    def run(self, force=False):
        """Run the backlog."""
        try:
            if force:
                self.forced = True

            # Push an update to any open Web UIs through the WebSocket
            ws.Message('QueueItemUpdate', self._to_json).push()
            self.search_backlog()
            ws.Message('QueueItemUpdate', self._to_json).push()

        except Exception:
            self.amActive = False
            raise
