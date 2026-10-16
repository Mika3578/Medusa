# coding=utf-8
"""Regression tests for slow Torznab search responses."""
from __future__ import unicode_literals

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
                               api_key='test', search_timeout=configured)
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
