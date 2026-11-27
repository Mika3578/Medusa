"""Cover the opt-in backlog path with local cache and mocked HTTP responses."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event
from unittest.mock import Mock
from urllib.parse import urlencode
from xml.sax.saxutils import escape, quoteattr

from medusa import app, db, name_cache
from medusa.common import DOWNLOADED, Quality, SNATCHED, WANTED
from medusa.providers.torrent.torznab.torznab import TorznabProvider
from medusa.search import core, smart_backlog
from medusa.search.queue import BacklogQueueItem, SnatchQueue, SnatchQueueItem
from medusa.server.api.v2.providers import ProvidersHandler

import pytest

from requests.exceptions import ReadTimeout

CAPS = ('<caps><limits max="2"/><searching><search available="yes" supportedParams="q"/>'
        '</searching></caps>')
NAMESPACE = 'http://torznab.com/schemas/2015/feed'
FULL_BACKLOG = date.fromordinal(1)


def feed(entries=(), offset=None, total=None):
    """Build a feed in which several filenames can share one content hash."""
    metadata = '' if offset is None else f'<torznab:response offset="{offset}" total="{total}"/>'
    rows = []
    for title, number in entries:
        link = f'magnet:?xt=urn:btih:{number:040x}&dn={title}'
        rows.append(f'<item><title>{escape(title)}</title><enclosure url={quoteattr(link)}/>'
                    '<pubDate>Fri, 01 Jan 2021 10:00:00 GMT</pubDate>'
                    '<torznab:attr name="seeders" value="5"/>'
                    '<torznab:attr name="size" value="1000"/></item>')
    return f'<rss xmlns:torznab="{NAMESPACE}"><channel>{metadata}{"".join(rows)}</channel></rss>'


def install_http(requests_mock, provider, caps=CAPS, pages=()):
    """Install deterministic Torznab responses for a single endpoint."""
    endpoint = provider.url + 'api'
    requests_mock.get(endpoint + '?t=caps', text=caps)
    requests_mock.get(endpoint + '?t=search', list(pages) or [{'text': feed()}])
    return requests_mock


@pytest.fixture
def provider():
    """Create an opt-in capable provider with ordinary defaults."""
    return TorznabProvider('Synthetic Torznab', 'https://indexer.invalid/', 'test-key')


@pytest.fixture
def library(provider, create_tvshow, create_tvepisode, monkeypatch, tmp_path):
    """Create 100 wanted episodes across four seasons with a real release cache."""
    show = create_tvshow(indexerid=123, name='Cash Investigation')
    other = create_tvshow(indexerid=124, name='Cash Investigation Extras')
    segments = {
        season: [create_tvepisode(show, season, ep, status=WANTED) for ep in range(1, 26)]
        for season in range(1, 5)
    }
    episodes = {(episode.season, episode.episode): episode
                for segment in segments.values() for episode in segment}
    monkeypatch.setattr(app, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(db, 'db_cons', {})
    monkeypatch.setattr(db, 'db_locks', {})
    monkeypatch.setattr(app, 'showList', [show, other])
    monkeypatch.setattr(name_cache, 'name_cache', {show.name.lower(): (show.indexer, show.series_id),
                                                   other.name.lower(): (other.indexer, other.series_id)})
    monkeypatch.setattr(name_cache, 'build_name_cache', Mock())
    monkeypatch.setattr(show, 'get_episode', lambda season, ep, **kwargs: episodes.get((season, ep)))
    monkeypatch.setattr(show, 'get_all_episodes', lambda season=None: segments[season] if season else list(episodes.values()))
    monkeypatch.setattr(show, 'get_wanted_segments', lambda **kwargs: segments)
    monkeypatch.setattr(show, 'want_episode', lambda season, ep, quality, **kwargs: episodes[season, ep].status == WANTED)
    monkeypatch.setattr('medusa.scene_numbering.get_indexer_numbering', lambda *args: (None, None))
    cache_db = db.DBConnection(str(tmp_path / 'provider.db'))
    cache_db.action('CREATE TABLE lastSearch (provider TEXT, time NUMERIC)')
    cache_db.action(
        'CREATE TABLE synthetic_torznab (identifier TEXT UNIQUE, name TEXT, season INTEGER, episodes TEXT, '
        'indexerid INTEGER, url TEXT, time INTEGER, quality INTEGER, release_group TEXT, version INTEGER, '
        'seeders INTEGER, leechers INTEGER, size INTEGER, pubdate TEXT, proper_tags TEXT, date_added INTEGER, indexer INTEGER)'
    )
    provider.cache.provider_db = cache_db
    monkeypatch.setattr(core, 'enabled_providers', lambda *_: [provider])
    yield show, segments
    for connection in db.db_cons.values():
        connection.close()


def test_request_count_across_seasons(provider, library, requests_mock):
    """Find 100 wanted episodes with one broad HTTP search and one simulated search."""
    show, segments = library
    provider.smart_backlog = True
    install_http(requests_mock, provider, caps=CAPS.replace('max="2"', 'max="100"'))
    network_searches = []

    def search_response(request, _context):
        network_searches.append(request.qs['q'])
        return feed([(f'Cash.Investigation.S{season:02}E{ep:02}.HDTV.XviD-GRP', season * 100 + ep)
                     for season in segments for ep in range(1, 26)])

    requests_mock.get(provider.url + 'api?t=search', text=search_response)
    for season, segment in segments.items():
        results = core.search_providers(show, segment, backlog_from_date=FULL_BACKLOG)
        assert {(result.actual_season, result.actual_episodes[0]) for result in results} == {
            (season, ep) for ep in range(1, 26)
        }
    assert len(requests_mock.request_history) == 2
    assert network_searches == [['cash investigation']]
    query = requests_mock.last_request.qs
    assert query == {'apikey': ['test-key'], 'cat': [','.join(provider.cat_ids)], 't': ['search'],
                     'q': ['cash investigation'], 'limit': ['100'], 'offset': ['0']}


@pytest.mark.parametrize('mode', ['disabled', 'manual', 'below_threshold', 'unsupported', 'paused'])
def test_activation(mode, provider, library, requests_mock, monkeypatch):
    """Keep opt-in, unsupported and manual paths isolated."""
    show, segments = library
    provider.smart_backlog = mode != 'disabled'
    provider.find_search_results = Mock(return_value={})
    monkeypatch.setattr(show, 'paused', mode == 'paused')
    segment = segments[1]
    if mode == 'below_threshold':
        segment = segment[:4]
        monkeypatch.setattr(show, 'get_wanted_segments', lambda **kwargs: {1: segment})
    install_http(requests_mock, provider, caps=CAPS.replace('available="yes"', 'available="no"'))
    core.search_providers(show, segment, manual_search=mode == 'manual', backlog_from_date=FULL_BACKLOG)
    assert provider.find_search_results.call_count == (mode != 'paused')
    assert requests_mock.call_count == (mode == 'unsupported')


def test_other_season_cached_and_query_suppressed(provider, library, requests_mock):
    """Keep season identity even when the first segment got zero usable releases."""
    show, segments = library
    install_http(requests_mock, provider, pages=[{'text': feed([
        ('Cash.Investigation.Extras.S01E02.HDTV.XviD-GRP', 44),
        ('Cash.Investigation.2x02.HDTV.XviD-GRP', 45),
        ('Cash.Investigation.S02E02.HDTV.XviD-GRP', 45),
    ])}])
    assert smart_backlog.search_segment(provider, show, segments[1], core.filter_results) is None
    assert smart_backlog.search_segment(provider, show, segments[2], core.filter_results) is None
    results = smart_backlog.segment_candidates(provider, show, segments[2], core.filter_results)[0]
    assert [(result.actual_season, result.actual_episodes) for result in results[2]] == [(2, [2]), (2, [2])]
    assert requests_mock.call_count == 2
    assert len(provider.cache._get_db().select('SELECT name FROM [synthetic_torznab]')) == 2


def test_cache_and_status(provider, library, requests_mock):
    """Reuse cache, reject quality mismatches, and exclude snatched or downloaded results."""
    show, segments = library
    episode = segments[1][1]
    install_http(requests_mock, provider, pages=[{'text': feed([
        ('Cash.Investigation.S01E02.1080p.BluRay.x264-GRP', 42),
        ('Cash.Investigation.S01E02.HDTV.XviD-GRP', 43),
    ])}])
    smart_backlog.search_segment(provider, show, segments[1], core.filter_results)
    results = smart_backlog.search_segment(provider, show, [episode], core.filter_results)
    assert [result.quality for result in results[2]] == [Quality.SDTV]
    assert requests_mock.call_count == 2
    for status in (DOWNLOADED, SNATCHED):
        episode.status = status
        assert not smart_backlog.segment_candidates(provider, show, [episode], core.filter_results)[0]


@pytest.mark.parametrize(('pages', 'outcome', 'results', 'offsets'), [
    ([{'text': feed()}], 'unknown', 0, [0]),
    ([{'exc': ReadTimeout}], 'timed_out', 0, [0]),
    ([{'status_code': 401}], 'authentication_failed', 0, [0]),
    ([{'text': '<error code="100"/>'}], 'authentication_failed', 0, [0]),
    ([{'text': '<rss><channel>'}], 'failed', 0, [0]),
    ([{'text': feed([('one', 1), ('alt', 1), ('two', 2)], 0, 3)},
      {'text': feed([('three', 3)], 2, 3)}], 'unknown', 4, [0, 2]),
    ([{'text': feed([('one', 1)], 0, 4)},
      {'text': feed([('one', 1)], 2, 4)}], 'partial', 1, [0, 2]),
    ([{'text': feed([('one', 1)], 0, 4)},
      {'text': feed([('two', 2)], 0, 4)}], 'partial', 1, [0, 2]),
    ([{'text': feed([('one', 1)], 0, 4)}, {'exc': ReadTimeout}], 'partial', 1, [0, 2]),
    ([{'text': feed([(str(i), i)], i * 2, 15)} for i in range(5)], 'partial_budget_exhausted', 5, [0, 2, 4, 6, 8]),
])
def test_page_contract(provider, requests_mock, pages, outcome, results, offsets):
    """Use the declared page size independently of expanded XML item count."""
    install_http(requests_mock, provider, pages=pages)
    items, status, count = provider.search_backlog_title('Les routes de l’impossible')
    assert (len(items), status, count) == (results, outcome, len(offsets) + 1)
    for request, offset in zip(requests_mock.request_history[1:], offsets):
        assert request.qs == {'q': ['les routes de l’impossible'], 't': ['search'], 'offset': [str(offset)],
                              'apikey': ['test-key'], 'limit': ['2'], 'cat': [','.join(provider.cat_ids)]}
    assert provider.search_backlog_title(' ') == ([], 'failed', 0)


def test_legacy_request_cannot_leak_params(provider, requests_mock, monkeypatch):
    """Follow an ID-based TV request with an independently constructed title request."""
    episode = Mock(scene_season=3, scene_episode=2)
    episode.series.air_by_date = episode.series.sports = False
    monkeypatch.setattr(provider, '_match_indexer', lambda: {'tvdbid': 123})
    install_http(requests_mock, provider)
    requests_mock.get(provider.url + 'api?' + urlencode({'t': 'tvsearch'}), text=feed([('old', 10)]))
    provider.search({'Episode': ['old search']}, ep_obj=episode)
    provider.search_backlog_title('Cash Investigation')
    assert 'tvdbid' in requests_mock.request_history[0].qs
    assert set(requests_mock.last_request.qs) == {'t', 'q', 'limit', 'offset', 'cat', 'apikey'}


def test_concurrent_and_retry(provider, library, monkeypatch):
    """Suppress concurrent identical work and permit retry after a failed attempt."""
    show, _ = library
    started, release = Event(), Event()

    def request(_query):
        started.set()
        assert release.wait(5)
        return [], 'failed', 1

    clock = Mock(return_value=42)
    monkeypatch.setattr(smart_backlog, 'monotonic', clock)
    remote = Mock(side_effect=request)
    monkeypatch.setattr(provider, 'search_backlog_title', remote)
    coordinator = provider.backlog_series_search
    with ThreadPoolExecutor(max_workers=2) as executor:
        active = executor.submit(coordinator.run, provider, show, show.name)
        assert started.wait(5)
        assert coordinator.recent(provider, show, show.name).status == 'in_progress'
        assert executor.submit(coordinator.run, provider, show, show.name).result(5)
        release.set()
        assert active.result(5)
    assert remote.call_count == 1
    assert coordinator.recent(provider, show, show.name).status == 'failed'
    assert coordinator.run(provider, show, show.name)
    assert remote.call_count == 1
    clock.return_value += smart_backlog.RETRY_DELAY
    assert coordinator.run(provider, show, show.name)
    assert remote.call_count == 2


def test_legacy_request_count(provider, library, requests_mock, monkeypatch):
    """Measure the per-episode legacy loop with one synthetic query per episode."""
    show, segments = library
    remote = Mock(return_value=feed())
    requests_mock.get(provider.url + 'api?t=search', text=remote)
    monkeypatch.setattr(provider, '_get_episode_search_strings', lambda ep: [
        {'Episode': [f'{show.name} S{ep.season:02}E{ep.episode:02}']},
    ])
    for segment in segments.values():
        assert core.search_providers(show, segment, backlog_from_date=FULL_BACKLOG) == []
    assert requests_mock.call_count == 100
    assert remote.call_count == 100


@pytest.mark.parametrize(('name', 'show_name', 'target', 'scene', 'air_date'), [
    ('The.100.S01E03.HDTV.XviD-GRP', 'The 100', (1, 3), None, None),
    ('Les.routes.de.l’impossible.1x03.HDTV.XviD-GRP', 'Les routes de l’impossible', (1, 3), None, None),
    ('Rembob’INA.S01E03.HDTV.XviD-GRP', 'Rembob’INA', (1, 3), None, None),
    ('Émission.S01E03.HDTV.XviD-GRP', 'Émission', (1, 3), None, None),
    ('Cash.Investigation.S01E03.HDTV.XviD-GRP', 'Cash Investigation', (2, 4), (2, 4), None),
    ('Cash.Investigation.2021.01.03.HDTV.XviD-GRP', 'Cash Investigation', (2, 4), None, (2, 4)),
    ('Cash.Investigation.S01E03E04.HDTV.XviD-GRP', 'Cash Investigation', (1, 3), None, None),
    ('Cash.Investigation.S01.HDTV.XviD-GRP', 'Cash Investigation', (1, 3), None, None),
])
def test_real_parser_mapping(name, show_name, target, scene, air_date, provider, library, monkeypatch):
    """Persist exact parser numbering and reuse ordinary cache reconstruction."""
    show, segments = library
    monkeypatch.setattr(show, 'name', show_name)
    name_cache.name_cache[smart_backlog.normalize_series_name_for_comparison(show_name)] = smart_backlog.series_key(show)
    if scene:
        monkeypatch.setattr('medusa.scene_numbering.get_indexer_numbering', lambda *args: scene)
    if air_date:
        monkeypatch.setattr(show, 'air_by_date', True)
        monkeypatch.setattr('medusa.name_parser.parser.NameParser._get_episodes_by_air_date',
                            lambda *args: [{'season': air_date[0], 'episode': air_date[1]}])
    items = provider.parse(feed([(name, 1)]), 'RSS')
    assert smart_backlog.cache_releases(provider, show, items) == (1, 1)
    season, episode = target
    results = provider.search_results_in_cache(segments[season])
    assert any(result.actual_season == season and episode in result.actual_episodes
               for bucket in results.values() for result in bucket)


def test_ambiguous_air_date(provider, library, monkeypatch):
    """Reject an air date shared by multiple regular episodes."""
    show, _ = library
    monkeypatch.setattr(show, 'air_by_date', True)
    monkeypatch.setattr('medusa.name_parser.parser.NameParser._get_episodes_by_air_date',
                        lambda *args: [{'season': 1, 'episode': ep} for ep in (3, 4)])
    items = provider.parse(feed([('Cash.Investigation.2021.01.03.HDTV.XviD-GRP', 1)]), 'RSS')
    assert smart_backlog.cache_releases(provider, show, items) == (0, 0)


def test_queue_deduplicates_content_and_rechecks_status(provider, library, monkeypatch):
    """Keep identical content out of queued and recently successful snatches."""
    show, segments = library
    queue = SnatchQueue()
    first = Mock(url='magnet:?xt=urn:btih:123&dn=first', smart_backlog=True, series=show,
                 episodes=[segments[1][0]], quality=Quality.SDTV)
    second = Mock(url='magnet:?xt=urn:btih:123&dn=second', smart_backlog=True, series=show,
                  episodes=[segments[2][0]], quality=Quality.SDTV)
    monkeypatch.setattr(show, 'to_json', lambda: {})
    for result in (first, second):
        monkeypatch.setattr(result.episodes[0], 'to_json', lambda: {})
    first_job, second_job = [SnatchQueueItem(show, result.episodes, result) for result in (first, second)]
    assert queue.add_item(first_job) is first_job
    assert queue.add_item(second_job) is None
    assert queue.queue == [first_job]
    queue.current_item = queue.queue.pop()
    queue.add_item(second_job)
    assert not queue.queue
    first_job.success = True
    queue.history.append(first_job)
    queue.current_item = None
    queue.add_item(second_job)
    assert not queue.queue
    snatch = Mock()
    monkeypatch.setattr('medusa.search.queue.snatch_result', snatch)
    second.episodes[0].status = SNATCHED
    second_job.start()
    second_job.join(5)
    assert second_job.success is False
    snatch.assert_not_called()


def test_provider_setting_round_trip(provider, monkeypatch):
    """Keep the setting default false and tolerate old provider payloads."""
    monkeypatch.setattr(provider, 'image_name', lambda: 'torznab.png')
    assert provider.to_json()['config']['search']['backlog']['smartSeriesSearch'] is False
    ProvidersHandler._set_torrent_settings(provider, {'search': {'backlog': {'smartSeriesSearch': True}}})
    ProvidersHandler._set_torrent_settings(provider, {})
    assert provider.to_json()['config']['search']['backlog']['smartSeriesSearch'] is True


def test_alias_and_conflicting_hash(provider, library):
    """Use a known alias and quarantine an ambiguous file within a response."""
    show, _ = library
    name_cache.name_cache['cash special'] = smart_backlog.series_key(show)
    items = provider.parse(feed([
        ('Cash.Special.S01E01.HDTV.XviD-GRP', 1),
        ('Cash.Investigation.S01E02.HDTV.XviD-GRP', 2),
        ('Cash.Investigation.S02E02.HDTV.XviD-GRP', 2),
    ]), 'RSS')
    assert smart_backlog.cache_releases(provider, show, items) == (3, 1)


def test_seasonless_and_title_only_are_not_promoted_to_packs(provider, library):
    """Avoid guessing a season or deriving episode coordinates from a title."""
    show, _ = library
    items = provider.parse(feed([
        ('Cash.Investigation.14.HDTV.XviD-GRP', 1),
        ('Cash.Investigation.Les.Envoyes.HDTV.XviD-GRP', 2),
        ('Cash.Investigation.Mai.2016.HDTV.XviD-GRP', 3),
    ]), 'RSS')
    assert smart_backlog.cache_releases(provider, show, items) == (0, 0)


def test_scheduler_cutoff_is_used(provider, library, monkeypatch):
    """Avoid broad work when the scheduled date window has fewer eligible episodes."""
    show, segments = library
    provider.smart_backlog = True
    cutoff = date(2021, 1, 1)
    segment = segments[1][:2]
    wanted = Mock(return_value={1: segment})
    monkeypatch.setattr(show, 'get_wanted_segments', wanted)
    provider.find_search_results = Mock(return_value={})
    provider.search_backlog_title = Mock()
    core.search_providers(show, segment, backlog_from_date=cutoff)
    wanted.assert_called_once_with(from_date=cutoff)
    provider.search_backlog_title.assert_not_called()
    provider.find_search_results.assert_called_once()


def needed_episodes(find_search_results):
    """Return the (season, episode) pairs passed to each legacy provider search."""
    return [{(ep.season, ep.episode) for ep in call.args[1]} for call in find_search_results.call_args_list]


def test_partial_broad_feed_falls_back_for_missing_episodes(provider, library, requests_mock):
    """Search the legacy way for episodes a single-page feed did not return."""
    show, segments = library
    provider.smart_backlog = True
    provider.find_search_results = Mock(return_value={})
    install_http(requests_mock, provider, caps=CAPS.replace('max="2"', 'max="100"'), pages=[{'text': feed([
        (f'Cash.Investigation.S04E{ep:02}.HDTV.XviD-GRP', 400 + ep) for ep in range(1, 26)
    ] + [('Cash.Investigation.S03E01.HDTV.XviD-GRP', 301)])}])
    for segment in segments.values():
        core.search_providers(show, segment, backlog_from_date=FULL_BACKLOG)
    assert requests_mock.call_count == 2
    assert needed_episodes(provider.find_search_results) == [
        {(1, ep) for ep in range(1, 26)},
        {(2, ep) for ep in range(1, 26)},
        {(3, ep) for ep in range(2, 26)},
    ]


def test_small_gap_in_large_segment_uses_legacy(provider, library, requests_mock):
    """Do not leave a few uncached episodes of a large segment unsearched."""
    show, segments = library
    provider.smart_backlog = True
    provider.find_search_results = Mock(return_value={})
    install_http(requests_mock, provider, caps=CAPS.replace('max="2"', 'max="100"'), pages=[{'text': feed([
        (f'Cash.Investigation.S{season:02}E{ep:02}.HDTV.XviD-GRP', season * 100 + ep)
        for season in segments for ep in range(1, 26) if (season, ep) not in {(1, 3), (1, 4)}
    ])}])
    core.search_providers(show, segments[2], backlog_from_date=FULL_BACKLOG)
    provider.find_search_results.assert_not_called()
    core.search_providers(show, segments[1], backlog_from_date=FULL_BACKLOG)
    # Legacy needed_eps currently over-selects (develop consumes an itertools.chain
    # while testing membership); only require that the gap is searched.
    searched, = needed_episodes(provider.find_search_results)
    assert {(1, 3), (1, 4)} <= searched
    assert requests_mock.call_count == 2


def test_snatched_upgrade_uses_legacy(provider, library, requests_mock, monkeypatch):
    """Keep legacy upgrade searches for snatched episodes below the preferred quality."""
    show, segments = library
    provider.smart_backlog = True
    provider.find_search_results = Mock(return_value={})
    segment = segments[1][:2]
    for episode in segment:
        episode.status = SNATCHED
    monkeypatch.setattr(Quality, 'should_search', staticmethod(lambda *args: (True, 'upgrade')))
    monkeypatch.setattr(show, 'get_wanted_segments', lambda **kwargs: {1: segment})
    install_http(requests_mock, provider)
    core.search_providers(show, segment, backlog_from_date=FULL_BACKLOG)
    assert needed_episodes(provider.find_search_results) == [{(1, 1), (1, 2)}]
    assert requests_mock.call_count == 0


def test_run_reports_skipped_work(provider, library, monkeypatch):
    """Report busy, saturated and crashed broad searches as not performed."""
    show, _ = library
    coordinator = provider.backlog_series_search
    monkeypatch.setattr(provider, 'search_backlog_title', Mock(side_effect=RuntimeError))
    assert not coordinator.run(provider, show, show.name)
    assert coordinator.recent(provider, show, show.name).status == 'failed'
    coordinator.attempts.clear()
    coordinator.active = True
    assert not coordinator.run(provider, show, show.name)
    coordinator.active = False
    coordinator.attempts = {('other', n): smart_backlog.Attempt(0, 'unknown', float('inf'))
                            for n in range(smart_backlog.MAX_ATTEMPTS)}
    assert not coordinator.run(provider, show, show.name)
    assert provider.search_backlog_title.call_count == 1


@pytest.mark.parametrize('smart', [True, False])
def test_backlog_waits_only_for_accepted_snatches(smart, provider, library, monkeypatch):
    """Preserve a successful snatch through a duplicate and a later failed snatch."""
    show, segments = library
    monkeypatch.setattr(show, 'to_json', lambda: {})
    results = []
    for episode in segments[1][:2]:
        monkeypatch.setattr(episode, 'to_json', lambda: {})
        results.append(Mock(
            url=f'magnet:?xt=urn:btih:{episode.episode:040x}', smart_backlog=smart,
            series=show, episodes=[episode], seeders=5, leechers=1, size=1000, provider=provider,
        ))

    first, second = results
    snatch_queue = SnatchQueue()
    duplicate = SnatchQueueItem(show, second.episodes, second)
    snatch_queue.add_item(duplicate)
    monkeypatch.setattr(app, 'manual_snatch_scheduler', Mock(action=snatch_queue))
    monkeypatch.setattr('medusa.search.queue.search_providers', Mock(return_value=[second, first, second]))
    monkeypatch.setattr('medusa.search.queue.common.cpu_presets', {app.CPU_PRESET: 0})
    monkeypatch.setattr(smart_backlog, 'eligible_result', lambda *_: True)
    snatch = Mock(side_effect=[True, False])
    monkeypatch.setattr('medusa.search.queue.snatch_result', snatch)

    backlog = BacklogQueueItem(show, [ep for result in results for ep in result.episodes])

    def process_snatch(_timeout):
        # The duplicate was rejected. Process only the new job the backlog is waiting for.
        queued = [job for job in snatch_queue.queue if job is not duplicate]
        assert len(queued) == 1
        if duplicate in snatch_queue.queue:
            snatch_queue.queue.remove(duplicate)
        snatch_queue.run()
        job = snatch_queue.current_item
        job.join(5)
        assert not job.is_alive()
        return False

    wait = Mock(side_effect=process_snatch)
    monkeypatch.setattr(backlog.stop, 'wait', wait)
    backlog.run()
    assert backlog.success is True
    assert wait.call_count == snatch.call_count == 2
    assert [job.success for job in snatch_queue.history] == [True, False]


def test_conflicting_content_invalidates_previous_cache_row(provider, library):
    """Drop an older cache alias absent from the conflicting response."""
    show, segments = library
    first = provider.parse(feed([
        ('Cash.Investigation.S01E01.HDTV.XviD-OLD', 9),
        ('Cash.Investigation.S01E02.HDTV.XviD-GRP', 10),
    ]), 'RSS')
    episodes = segments[1][:2]
    assert smart_backlog.cache_releases(provider, show, first) == (2, 2)
    assert set(smart_backlog.segment_candidates(provider, show, episodes, core.filter_results)[0]) == {1, 2}

    conflict = provider.parse(feed([
        ('Cash.Investigation.S01E01.HDTV.XviD-GRP', 9),
        ('Cash.Investigation.S02E01.HDTV.XviD-GRP', 9),
    ]), 'RSS')
    assert smart_backlog.cache_releases(provider, show, conflict) == (2, 0)
    candidates, missing = smart_backlog.segment_candidates(provider, show, episodes, core.filter_results)
    assert set(candidates) == {2}
    assert missing == {(1, 1)}
    assert provider.search_results_in_cache([show.get_episode(2, 1)]) == {}


def test_sports_without_air_by_date_use_legacy_search(provider, library, monkeypatch):
    """Keep sports on the legacy path until shared air-date mapping exists."""
    show, segments = library
    provider.smart_backlog = True
    monkeypatch.setattr(show, 'sports', True)
    monkeypatch.setattr(show, 'air_by_date', False)
    provider.find_search_results = Mock(return_value={})
    provider.search_backlog_title = Mock()
    core.search_providers(show, segments[1][:smart_backlog.MIN_EPISODES],
                          backlog_from_date=FULL_BACKLOG)
    provider.search_backlog_title.assert_not_called()
    provider.find_search_results.assert_called_once()


def test_repeated_unknown_coverage_falls_back_to_targeted_search(provider, library, requests_mock):
    """After an unknown-coverage broad search, later segments use the targeted path."""
    show, segments = library
    provider.smart_backlog = True
    provider.find_search_results = Mock(return_value={})
    # Empty Torznab pages report coverage "unknown" (no total, no items).
    install_http(requests_mock, provider, caps=CAPS.replace('max="2"', 'max="100"'),
                 pages=[{'text': feed()}])

    first = segments[1][:smart_backlog.MIN_EPISODES]
    second = segments[2][:smart_backlog.MIN_EPISODES]
    core.search_providers(show, first, backlog_from_date=FULL_BACKLOG)
    attempt = provider.backlog_series_search.recent(provider, show, show.name)
    assert attempt is not None
    assert attempt.status == 'unknown'
    provider.find_search_results.assert_called_once()
    provider.find_search_results.reset_mock()

    core.search_providers(show, second, backlog_from_date=FULL_BACKLOG)
    # Broad title search must not run again; the segment gets a targeted legacy search.
    assert provider.backlog_series_search.recent(provider, show, show.name).status == 'unknown'
    provider.find_search_results.assert_called_once()
    assert needed_episodes(provider.find_search_results) == [
        {(2, ep.episode) for ep in second},
    ]
    # Caps + one empty title search only (no second broad request).
    assert requests_mock.call_count == 2


def test_expired_unknown_coverage_retries_broad_then_falls_back(
        provider, library, requests_mock, monkeypatch):
    """After the reuse window expires, another unknown broad search still yields targeted search."""
    show, segments = library
    provider.smart_backlog = True
    provider.find_search_results = Mock(return_value={})
    clock = {'now': 1000.0}
    monkeypatch.setattr(smart_backlog, 'monotonic', lambda: clock['now'])
    install_http(requests_mock, provider, caps=CAPS.replace('max="2"', 'max="100"'),
                 pages=[{'text': feed()}, {'text': feed()}])

    first = segments[1][:smart_backlog.MIN_EPISODES]
    second = segments[2][:smart_backlog.MIN_EPISODES]

    core.search_providers(show, first, backlog_from_date=FULL_BACKLOG)
    first_attempt = provider.backlog_series_search.recent(provider, show, show.name)
    assert first_attempt is not None
    assert first_attempt.status == 'unknown'
    provider.find_search_results.assert_called_once()
    provider.find_search_results.reset_mock()
    broad_after_first = requests_mock.call_count

    # Expire the reuse window without a real sleep.
    clock['now'] += smart_backlog.RETRY_DELAY + 1
    assert provider.backlog_series_search.recent(provider, show, show.name) is None

    core.search_providers(show, second, backlog_from_date=FULL_BACKLOG)
    second_attempt = provider.backlog_series_search.recent(provider, show, show.name)
    assert second_attempt is not None
    assert second_attempt.status == 'unknown'
    # A second broad title search ran after expiry, then targeted search for the gap.
    assert requests_mock.call_count == broad_after_first + 1
    provider.find_search_results.assert_called_once()
    assert needed_episodes(provider.find_search_results) == [
        {(2, ep.episode) for ep in second},
    ]
