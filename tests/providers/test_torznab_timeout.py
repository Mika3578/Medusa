# coding=utf-8
"""Regression tests for slow Torznab search responses and aMuTorrent-style caps."""
from __future__ import unicode_literals

from types import SimpleNamespace

import pytest

from medusa.providers.torrent.torznab.torznab import TorznabProvider
from medusa.server.api.v2.providers import ProvidersHandler


@pytest.mark.parametrize('configured, expected', [
    (None, 30),
    ('invalid', 30),
    (-10, 30),
    (30, 30),
    (180, 180),
    ('480', 480),
    (9999, 600),
])
def test_torznab_search_timeout_is_bounded(configured, expected, monkeypatch):
    provider = TorznabProvider('Test Torznab', url='http://localhost/indexer/amule/',
                               api_key='test', search_timeout=configured,
                               cap_tv_search=['q'])
    seen = []

    def get(url, **kwargs):
        seen.append((url, kwargs))
        return None

    monkeypatch.setattr(provider.session, 'get', get)

    assert provider.search({'Episode': ['Example.Show.S01E01']}, force_query=True) == []
    assert len(seen) == 1
    assert seen[0][1]['timeout'] == (30, expected)
    assert seen[0][1]['params']['t'] == 'search'


def test_torznab_timeout_exposed_in_provider_json(monkeypatch):
    from medusa import app

    monkeypatch.setattr(app, 'THEME_DATA_ROOT', '')
    provider = TorznabProvider('Test Torznab', search_timeout=180)
    assert provider.to_json()['config']['search']['timeout'] == 180


def test_torznab_timeout_patch_normalizes_and_preserves_missing_field():
    provider = TorznabProvider('Test Torznab', search_timeout=180)
    ProvidersHandler._set_common_settings(provider, {'search': {'timeout': 1000}})
    assert provider.search_timeout == 600

    ProvidersHandler._set_common_settings(provider, {'search': {}})
    assert provider.search_timeout == 600


def _episode_stub(title='Example Show', season=1, episode=5):
    series = SimpleNamespace(
        air_by_date=False,
        sports=False,
        anime=False,
        get_all_possible_names=lambda season=None: {title},
    )
    return SimpleNamespace(
        series=series,
        scene_season=season,
        scene_episode=episode,
        airdate=None,
    )


def test_torznab_uses_sonarr_like_tvsearch_for_q_season_ep_caps(monkeypatch):
    """aMuTorrent advertises q,season,ep — Medusa must not free-text S01E01 queries."""
    provider = TorznabProvider(
        'aMuTorrent',
        url='http://localhost/indexer/amule/',
        api_key='test',
        search_timeout=180,
        cap_tv_search=['q', 'season', 'ep'],
    )
    seen = []

    def get(url, **kwargs):
        seen.append(kwargs)
        return None

    monkeypatch.setattr(provider.session, 'get', get)

    results = provider.search(
        {'Episode': ['Example.Show.S01E05']},
        ep_obj=_episode_stub(),
    )

    assert results == []
    assert len(seen) == 1
    params = seen[0]['params']
    assert params['t'] == 'tvsearch'
    assert params['q'] == 'Example Show'
    assert params['season'] == 1
    assert params['ep'] == 5
    assert 'tvdbid' not in params
    assert seen[0]['timeout'] == (30, 180)


def test_torznab_id_search_still_preferred_when_caps_include_tvdbid(monkeypatch):
    from medusa.indexers.config import INDEXER_TVDBV2

    provider = TorznabProvider(
        'Jackett',
        url='http://localhost/torznab/',
        api_key='test',
        cap_tv_search=['tvdbid', 'q', 'season', 'ep'],
    )
    provider.series = SimpleNamespace(
        indexer=INDEXER_TVDBV2,
        indexerid=12345,
        externals={},
    )
    seen = []

    def get(url, **kwargs):
        seen.append(kwargs)
        return None

    monkeypatch.setattr(provider.session, 'get', get)

    provider.search({'Episode': ['Example.Show.S01E05']}, ep_obj=_episode_stub())

    # Empty ID response falls back to structured text tvsearch (force_query).
    assert len(seen) == 2
    id_params = seen[0]['params']
    assert id_params['t'] == 'tvsearch'
    assert id_params['tvdbid'] == 12345
    assert id_params['season'] == 1
    assert id_params['ep'] == 5
    assert 'q' not in id_params

    text_params = seen[1]['params']
    assert text_params['t'] == 'tvsearch'
    assert text_params['q'] == 'Example Show'
    assert text_params['season'] == 1
    assert text_params['ep'] == 5
    assert 'tvdbid' not in text_params


def test_title_query_strips_episode_markers():
    assert TorznabProvider._title_query_from_search_string('Example.Show.S01E05') == 'Example Show'
    assert TorznabProvider._title_query_from_search_string('Example Show 1x05') == 'Example Show'
    assert TorznabProvider._title_query_from_search_string('Example Show Season 3') == 'Example Show'
