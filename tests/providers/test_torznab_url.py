# coding=utf-8
"""Provider test code for the Torznab provider api url construction."""
from __future__ import unicode_literals

from medusa.providers.torrent.torznab.torznab import TorznabProvider

import pytest


@pytest.mark.parametrize('p', [
    {  # p0: base url without trailing slash, with a nested path (issue #12361)
        'url': 'http://localhost:4000/indexer/amule',
        'expected': 'http://localhost:4000/indexer/amule/api',
    },
    {  # p1: base url with trailing slash
        'url': 'http://localhost:4000/indexer/amule/',
        'expected': 'http://localhost:4000/indexer/amule/api',
    },
    {  # p2: root host, without trailing slash
        'url': 'http://localhost',
        'expected': 'http://localhost/api',
    },
    {  # p3: root host, with trailing slash
        'url': 'http://localhost/',
        'expected': 'http://localhost/api',
    },
    {  # p4: base url that already points at the api endpoint
        'url': 'http://localhost:4000/indexer/amule/api',
        'expected': 'http://localhost:4000/indexer/amule/api',
    },
    {  # p5: api endpoint with trailing slash should not result in a doubled api path
        'url': 'http://localhost:4000/indexer/amule/api/',
        'expected': 'http://localhost:4000/indexer/amule/api/',
    },
    {  # p6: base url with a query string is assumed to be a full api url
        'url': 'http://localhost:4000/indexer/amule?param=value',
        'expected': 'http://localhost:4000/indexer/amule?param=value',
    },
])
def test_torznab_search_url_keeps_base_path(p, monkeypatch):
    """The configured base url path should be preserved when the api url is built."""
    provider = TorznabProvider('Test Torznab', url=p['url'], api_key='test')
    urls = []

    def get(url, **kwargs):
        urls.append(url)
        return None

    monkeypatch.setattr(provider.session, 'get', get)

    provider.search({'Episode': ['Example.Show.S01E01']}, force_query=True)

    assert urls == [p['expected']]


def test_torznab_caps_url_keeps_base_path(monkeypatch):
    """Capability discovery should use the same api url, with the base path preserved."""
    provider = TorznabProvider('Test Torznab', url='http://localhost:4000/indexer/amule', api_key='test')
    urls = []

    def get(url, **kwargs):
        urls.append(url)
        return None

    monkeypatch.setattr(provider.session, 'get', get)

    provider.get_capabilities()

    assert urls == ['http://localhost:4000/indexer/amule/api']
