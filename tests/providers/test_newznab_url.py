# coding=utf-8
"""Provider test code for the Newznab provider api url construction."""
from __future__ import unicode_literals

from medusa.providers.nzb.newznab import NewznabProvider

import pytest


@pytest.mark.parametrize('p', [
    {  # p0: base url without trailing slash, with a nested path
        'url': 'http://localhost:9000/nzbhydra2',
        'expected': 'http://localhost:9000/nzbhydra2/api',
    },
    {  # p1: base url with trailing slash
        'url': 'http://localhost:9000/nzbhydra2/',
        'expected': 'http://localhost:9000/nzbhydra2/api',
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
        'url': 'http://localhost:9000/nzbhydra2/api',
        'expected': 'http://localhost:9000/nzbhydra2/api',
    },
    {  # p5: api endpoint with trailing slash should not result in a doubled api path
        'url': 'http://localhost:9000/nzbhydra2/api/',
        'expected': 'http://localhost:9000/nzbhydra2/api/',
    },
    {  # p6: base url with a query string is assumed to be a full api url
        'url': 'http://localhost:9000/nzbhydra2?param=value',
        'expected': 'http://localhost:9000/nzbhydra2?param=value',
    },
])
def test_newznab_search_url_keeps_base_path(p, monkeypatch):
    """The configured base url path should be preserved when the api url is built."""
    provider = NewznabProvider('Test Newznab', url=p['url'], api_key='test')
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get('params') or {}))
        return None

    monkeypatch.setattr(provider.session, 'get', get)

    provider.search({'Episode': ['Example.Show.S01E01']})

    # The provider requests caps first and falls back to a force_query search.
    assert calls
    search_calls = [url for url, params in calls if params.get('t') == 'search']
    assert search_calls
    assert all(url == p['expected'] for url, _ in calls)


def test_newznab_caps_url_keeps_base_path(monkeypatch):
    """Capability discovery should use the same api url, with the base path preserved."""
    provider = NewznabProvider('Test Newznab', url='http://localhost:9000/nzbhydra2', api_key='test')
    urls = []

    def get(url, **kwargs):
        urls.append(url)
        return None

    monkeypatch.setattr(provider.session, 'get', get)

    provider.get_capabilities()

    assert urls == ['http://localhost:9000/nzbhydra2/api']
