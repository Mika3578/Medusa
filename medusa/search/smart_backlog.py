"""Coordinate title-only backlog searches and populate the provider release cache."""

import logging
import threading
from collections import namedtuple
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from medusa import app
from medusa.common import Quality, SNATCHED, SNATCHED_BEST, SNATCHED_PROPER
from medusa.logger.adapters.style import BraceAdapter
from medusa.name_parser.parser import InvalidNameException, InvalidShowException, NameParser
from medusa.name_parser.series_name import normalize_series_name_for_comparison

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())

MIN_EPISODES = 5
RETRY_DELAY = 300
MAX_ATTEMPTS = 256
Attempt = namedtuple('Attempt', 'started status retry_at')


def series_key(series):
    """Identify a series in its indexer's namespace."""
    return series.indexer, series.series_id


def content_key(result):
    """Identify magnet content independently of its display name."""
    if result.url.startswith('magnet:?'):
        hashes = parse_qs(urlsplit(result.url).query).get('xt', ())
        for value in hashes:
            if value.lower().startswith('urn:btih:'):
                return 'btih', value.lower()
    return 'url', result.url


class SeriesSearch:
    """Track a bounded number of attempts for one provider instance."""

    def __init__(self):
        """Initialize process-local coordination."""
        self.lock = threading.Lock()
        self.attempts = {}
        self.active = False

    def attempt_key(self, provider, series, query):
        """Identify a title query within a provider and canonical series."""
        return provider.get_id(), *series_key(series), 'series', query.casefold()

    def recent(self, provider, series, query):
        """Return the recent attempt, including an in-progress attempt."""
        with self.lock:
            attempt = self.attempts.get(self.attempt_key(provider, series, query))
            return attempt if attempt and attempt.retry_at > monotonic() else None

    def run(self, provider, series, query):
        """Cache broad results once per series and retry window."""
        key = self.attempt_key(provider, series, query)
        started = monotonic()
        with self.lock:
            self.attempts = {k: v for k, v in self.attempts.items() if v.retry_at > started}
            if key in self.attempts:
                return self.attempts[key].status != 'unsupported'
            if self.active or len(self.attempts) >= MAX_ATTEMPTS:
                # Nothing was searched: let the caller fall back to the legacy search.
                return False
            self.active = True
            self.attempts[key] = Attempt(started, 'in_progress', float('inf'))

        status = 'failed'
        try:
            items, coverage, requests = provider.search_backlog_title(query)
            parsed, cached = cache_releases(provider, series, items) if items else (0, 0)
            status = coverage
            log.debug('Smart backlog {key}: {status}, {requests} requests, {total} items, '
                      '{parsed} matched, {cached} cached, {rejected} rejected, retry in {delay}s',
                      key=key, status=status, requests=requests, total=len(items),
                      parsed=parsed, cached=cached, rejected=len(items) - cached, delay=RETRY_DELAY)
            return status != 'unsupported'
        except Exception as error:
            log.warning('Smart backlog {key} failed ({error})', key=key, error=type(error).__name__)
            return False
        finally:
            with self.lock:
                self.attempts[key] = Attempt(started, status, monotonic() + RETRY_DELAY)
                self.active = False


def _purge_cache_identifiers(provider, identifiers):
    """Remove previously cached rows whose content mapping is no longer safe."""
    identifiers = [identifier for identifier in identifiers if identifier]
    if not identifiers:
        return
    cache_db = provider.cache._get_db()
    cache_db.mass_action([
        ['DELETE FROM [{provider}] WHERE identifier=?'.format(provider=provider.cache.provider_id),
         [identifier]]
        for identifier in identifiers
    ])


def cache_releases(provider, series, items):
    """Resolve supplied releases independently and cache only unambiguous mappings."""
    parser = NameParser(parse_method='anime' if series.is_anime else 'normal', local_air_dates_only=True)
    other_names = {
        normalize_series_name_for_comparison(name)
        for show in app.showList if series_key(show) != series_key(series)
        for name in [show.name] + [alias.title for alias in show.aliases]
    }
    known = {(episode.season, episode.episode) for episode in series.get_all_episodes()}
    mappings = {}
    content_identifiers = {}
    conflicting_content = set()
    matches = []
    for item in items:
        result = provider.get_result(series, item=item)
        content = content_key(result)
        content_identifiers.setdefault(content, set()).add(result.identifier)
        try:
            parsed = parser.parse(result.name, cache_result=False, use_cache=False)
        except (InvalidNameException, InvalidShowException):
            continue
        parsed_name = normalize_series_name_for_comparison(parsed.series_name)
        release_name = normalize_series_name_for_comparison(result.name)
        if (series_key(parsed.series) != series_key(series) or parsed_name in other_names
                or any(name.startswith(parsed_name + ' ') and release_name.startswith(name + ' ')
                       for name in other_names)):
            conflicting_content.add(content)
            continue
        if parsed.season_number is None or not (parsed.guess.get('season') is not None
                                                or parsed.is_air_by_date
                                                or (series.is_anime and parsed.ab_episode_numbers)):
            continue
        if (series.air_by_date or series.sports) and not parsed.is_air_by_date:
            continue
        season = parsed.season_number
        episodes = tuple(sorted(parsed.episode_numbers))
        if not episodes:
            if parsed.is_air_by_date or not any(s == season for s, _ in known):
                continue
        elif any((season, episode) not in known for episode in episodes):
            continue
        mappings.setdefault(content, set()).add((season, episodes))
        matches.append((content, result, parsed))

    ambiguous_content = {
        content for content, targets in mappings.items() if len(targets) != 1
    } | conflicting_content
    _purge_cache_identifiers(
        provider,
        {identifier for content in ambiguous_content
         for identifier in content_identifiers.get(content, ())},
    )

    entries = {}
    for content, result, parsed in matches:
        if content in ambiguous_content or result.identifier in entries:
            continue
        entry = provider.cache.add_cache_entry(result, parsed, log_url=False)
        if entry:
            entries[result.identifier] = entry
    if entries:
        provider.cache._get_db().mass_action(list(entries.values()))
    return len(matches), len(entries)


def wanted_episode(episode, series):
    """Apply the legacy backlog rule, including quality upgrades of snatched episodes."""
    return Quality.should_search(episode.status, episode.quality, series, episode.manually_searched)[0]


def eligible_episode(episode, series):
    """Recheck snatch eligibility: a smart result never replaces a pending snatch."""
    return (episode.status not in (SNATCHED, SNATCHED_BEST, SNATCHED_PROPER)
            and wanted_episode(episode, series))


def eligible_result(result):
    """Require each episode to remain eligible for this release quality."""
    return bool(result.episodes and not result.series.paused and all(
        eligible_episode(episode, result.series)
        and result.series.want_episode(episode.season, episode.episode, result.quality)
        for episode in result.episodes
    ))


def segment_candidates(provider, series, episodes, filter_results):
    """Use the existing cache and keep candidates within a single wanted segment.

    Episodes that remain wanted but cannot take a smart result (snatched episodes
    waiting for an upgrade) are reported as missing so the legacy search handles them.
    """
    episodes = [ep for ep in episodes if wanted_episode(ep, series)]
    if not episodes:
        return {}, set()
    wanted = {(ep.season, ep.episode) for ep in episodes}
    candidates = {}
    for number, results in provider.search_results_in_cache(episodes).items():
        scoped = [
            result for result in results if series_key(result.series) == series_key(series)
            and result.actual_episodes
            and all((result.actual_season, ep) in wanted for ep in result.actual_episodes)
        ]
        accepted = [result for result in filter_results(scoped) if eligible_result(result)]
        for result in accepted:
            result.smart_backlog = True
        if accepted:
            candidates[number] = accepted
    covered = {(result.actual_season, ep) for results in candidates.values()
               for result in results for ep in result.actual_episodes}
    return candidates, wanted - covered


def search_segment(provider, series, episodes, filter_results, from_date=None):
    """Return cache candidates when they cover the segment, or None to use legacy search.

    The broad title search only refreshes the provider cache. Any episode it does not
    cover is left to the legacy search, which reads that cache first and only queries
    the provider for the episodes still needed, so coverage never drops below legacy.
    """
    if not episodes or len({episode.season for episode in episodes}) != 1:
        return None
    if series.paused:
        return {}
    # Sports date-only releases are not mapped by NameParser unless air_by_date is set.
    # Keep the legacy provider path until sports air-date mapping is shared.
    if series.sports and not series.air_by_date:
        return None
    query = ' '.join(series.name.split())
    if not query:
        return None
    season = episodes[0].season
    candidates, missing = segment_candidates(provider, series, episodes, filter_results)
    if not missing:
        log.debug('Smart backlog {provider} {series}: season {season} covered by cache',
                  provider=provider.get_id(), series=series_key(series), season=season)
        return candidates

    coordinator = provider.backlog_series_search
    attempt = coordinator.recent(provider, series, query)
    if attempt:
        log.debug('Smart backlog {provider} {series}: previous attempt {status}, {missing} unresolved in season {season},'
                  ' using legacy search', provider=provider.get_id(), series=series_key(series),
                  status=attempt.status, missing=len(missing), season=season)
        return None

    # Reapply the scheduler's eligibility rules for the series. Always read the
    # cache one season at a time, since cache candidate keys are episode numbers.
    unresolved = set(missing)
    segments = series.get_wanted_segments(from_date=from_date) if len(unresolved) < MIN_EPISODES else {}
    for other_season, segment in segments.items():
        if len(unresolved) >= MIN_EPISODES:
            break
        if other_season == season and {(ep.season, ep.episode) for ep in segment}.issubset(
                {(ep.season, ep.episode) for ep in episodes}):
            continue
        unresolved.update(segment_candidates(provider, series, segment, filter_results)[1])
    log.debug('Smart backlog {provider} {series}: {missing} unresolved (threshold {threshold})',
              provider=provider.get_id(), series=series_key(series), missing=len(unresolved), threshold=MIN_EPISODES)
    if len(unresolved) < MIN_EPISODES:
        return None

    coordinator.run(provider, series, query)
    candidates, missing = segment_candidates(provider, series, episodes, filter_results)
    if missing:
        log.debug('Smart backlog {provider} {series}: {missing} unresolved in season {season} after broad search,'
                  ' using legacy search', provider=provider.get_id(), series=series_key(series),
                  missing=len(missing), season=season)
        return None
    return candidates
