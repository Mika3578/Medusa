# coding=utf-8
"""Regression tests for absolute episode matching (ED2K-style releases)."""
from __future__ import unicode_literals

from unittest.mock import Mock

import guessit

from medusa import helpers, scene_exceptions, scene_numbering
from medusa.name_parser.parser import NameParser
from medusa.tv.episode import Episode

import pytest


@pytest.fixture
def mock_absolute_db_lookup(monkeypatch):
    """Patch DBConnection.select for absolute-number season/episode lookup."""
    def _apply(rows):
        mock_db = Mock()
        mock_db.select = Mock(return_value=rows)
        monkeypatch.setattr('medusa.tv.series.db.DBConnection', Mock(return_value=mock_db))
        return mock_db

    return _apply


def test_get_episode_resolves_absolute_number_for_non_anime(create_tvshow, create_tvepisode,
                                                            mock_absolute_db_lookup, monkeypatch):
    """Shows with TMDB absolute_number in DB should resolve SxxExx without is_anime."""
    mock_absolute_db_lookup([{'season': 1, 'episode': 2}])
    monkeypatch.setattr(Episode, '_specify_episode', lambda self, season, episode: None)

    show = create_tvshow(name=u'Invasion du Troisième Type', is_anime=False, indexerid=102165)
    ep = show.get_episode(absolute_number=2)

    assert ep is not None
    assert ep.season == 1
    assert ep.episode == 2


def test_get_episode_resolves_absolute_number_for_anime(create_tvshow, mock_absolute_db_lookup, monkeypatch):
    """Anime shows keep working with absolute_number lookup."""
    mock_absolute_db_lookup([{'season': 4, 'episode': 8}])
    monkeypatch.setattr(Episode, '_specify_episode', lambda self, season, episode: None)

    show = create_tvshow(name=u'Cardcaptor Sakura', is_anime=True)
    ep = show.get_episode(absolute_number=78)

    assert ep is not None
    assert ep.season == 4
    assert ep.episode == 8


def test_get_episode_unknown_absolute_number_returns_none(create_tvshow, mock_absolute_db_lookup):
    mock_absolute_db_lookup([])
    show = create_tvshow(name=u'Invasion du Troisième Type', is_anime=False)
    ep = show.get_episode(absolute_number=999)
    assert ep is None


class FakeAbsoluteNumberingDB(object):
    """Minimal main DB stub: only the indexer absolute_number lookup returns rows."""

    def __init__(self, absolute_map):
        self.absolute_map = absolute_map

    def select(self, query, args=None):
        if 'FROM tv_episodes' in query and 'AND absolute_number = ?' in query:
            mapping = self.absolute_map.get(args[-1])
            if mapping:
                return [{'season': mapping[0], 'episode': mapping[1]}]
        return []


@pytest.mark.parametrize('p', [
    {
        # Real ED2K-style filename (Guessit returns both episode and absolute_episode).
        'name': u'Invasion du troisième type 02 FR ovni.mp4',
        'guess': None,
        'absolute_map': {2: (1, 2)},
        'expected': (1, [2]),
    },
    {
        # Stored absolute number 14 is S02E02: it must not become S01E14.
        'name': u'Invasion du troisième type 14 FR ovni.mp4',
        'guess': None,
        'absolute_map': {14: (2, 2)},
        'expected': (2, [2]),
    },
    {
        # Without stored absolute numbering, keep the season 1 fallback.
        'name': u'Invasion du troisième type 14 FR ovni.mp4',
        'guess': None,
        'absolute_map': {},
        'expected': (1, [14]),
    },
    {
        # Guessit result with only an absolute_episode.
        'name': u'invasion-du-troisieme-type-14',
        'guess': {'title': u'Invasion du troisième type', 'absolute_episode': 14, 'type': 'episode'},
        'absolute_map': {14: (2, 2)},
        'expected': (2, [2]),
    },
    {
        'name': u'invasion-du-troisieme-type-14',
        'guess': {'title': u'Invasion du troisième type', 'absolute_episode': 14, 'type': 'episode'},
        'absolute_map': {},
        'expected': (1, [14]),
    },
])
def test_parse_non_anime_seasonless_release_uses_absolute_numbering(p, create_tvshow, monkeypatch):
    """Season-less releases of non-anime shows resolve through production dispatch, never _parse_anime."""
    series = create_tvshow(name=u'Invasion du Troisième Type', is_anime=False, indexerid=102165)
    monkeypatch.setattr(helpers, 'get_show', Mock(return_value=series))
    monkeypatch.setattr(scene_exceptions, 'get_season_from_name', Mock(return_value=None))
    monkeypatch.setattr(scene_numbering.db, 'DBConnection', Mock(return_value=FakeAbsoluteNumberingDB(p['absolute_map'])))
    parse_anime = Mock(side_effect=AssertionError('_parse_anime must not be used for non-anime shows'))
    monkeypatch.setattr(NameParser, '_parse_anime', parse_anime)
    if p['guess'] is not None:
        monkeypatch.setattr(guessit, 'guessit', Mock(return_value=p['guess']))

    result = NameParser().parse(p['name'], cache_result=False, use_cache=False)

    assert result.series is series
    assert p['expected'] == (result.season_number, result.episode_numbers)
    assert not parse_anime.called
