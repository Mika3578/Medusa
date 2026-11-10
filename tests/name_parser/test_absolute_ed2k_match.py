# coding=utf-8
"""Regression tests for absolute episode matching (ED2K-style releases)."""
from __future__ import unicode_literals

from unittest.mock import Mock

import guessit
import pytest

from medusa.name_parser.parser import NameParser
from medusa.tv.episode import Episode


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


@pytest.mark.parametrize('p', [
    {
        'name': u'Invasion du troisième type 02 FR ovni.mp4',
        'mocks': [
            ('medusa.scene_exceptions.get_season_from_name', None),
            ('medusa.scene_numbering.get_indexer_numbering', (None, None)),
        ],
        'expected': ([2], [1], []),
    },
])
def test_non_anime_ed2k_filename_maps_to_season_one(p, create_tvshow, monkeypatch_function_return):
    """Guessit anime flag must not force _parse_anime when the show is not marked anime."""
    monkeypatch_function_return(p['mocks'])

    parser = NameParser()
    guess = guessit.guessit(p['name'])
    result = parser.to_parse_result(p['name'], guess)
    result.series = create_tvshow(name=u'Invasion du Troisième Type', is_anime=False)
    result.series.scene = False

    if result.series.is_anime:
        actual = parser._parse_anime(result)
    else:
        actual = parser._parse_series(result)

    assert p['expected'] == actual
