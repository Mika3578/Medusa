# coding=utf-8
"""Regression tests for absolute episode matching (ED2K-style releases)."""
from __future__ import unicode_literals

import sqlite3
from unittest.mock import Mock

import guessit

from medusa import helpers, scene_exceptions, scene_numbering
from medusa.name_parser.parser import InvalidNameException, NameParser
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


class SQLiteMainDB(object):
    """Temporary SQLite main DB using the real ``scene_numbering`` and ``tv_episodes`` schemas."""

    SCHEMA = (
        'CREATE TABLE scene_numbering(indexer TEXT, indexer_id INTEGER, season INTEGER, episode INTEGER, '
        'scene_season INTEGER, scene_episode INTEGER, absolute_number NUMERIC, scene_absolute_number NUMERIC, '
        'PRIMARY KEY(indexer_id, season, episode));',
        'CREATE TABLE tv_episodes(episode_id INTEGER PRIMARY KEY, showid NUMERIC, indexerid INTEGER, '
        'indexer INTEGER, name TEXT, season NUMERIC, episode NUMERIC, description TEXT, airdate NUMERIC, '
        'hasnfo NUMERIC, hastbn NUMERIC, status NUMERIC, location TEXT, file_size NUMERIC, release_name TEXT, '
        'subtitles TEXT, subtitles_searchcount NUMERIC, subtitles_lastsearch TIMESTAMP, is_proper NUMERIC, '
        'scene_season NUMERIC, scene_episode NUMERIC, absolute_number NUMERIC, scene_absolute_number NUMERIC, '
        'version NUMERIC DEFAULT -1, release_group TEXT);',
    )

    def __init__(self, path, series):
        self.series = series
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        for statement in self.SCHEMA:
            self.connection.execute(statement)

    def add_episode(self, season, episode, absolute_number=0, scene_absolute_number=0):
        self.connection.execute(
            'INSERT INTO tv_episodes (showid, indexer, season, episode, absolute_number, scene_absolute_number) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            [self.series.series_id, self.series.indexer, season, episode, absolute_number, scene_absolute_number]
        )

    def add_custom_absolute(self, absolute_number, scene_absolute_number):
        # Same rows as scene_numbering.set_scene_numbering() writes for an absolute mapping.
        self.connection.execute(
            'INSERT OR IGNORE INTO scene_numbering (indexer, indexer_id, absolute_number) VALUES (?,?,?)',
            [self.series.indexer, self.series.series_id, absolute_number]
        )
        self.connection.execute(
            'UPDATE scene_numbering SET scene_absolute_number = ? '
            'WHERE indexer = ? and indexer_id = ? and absolute_number = ?',
            [scene_absolute_number, self.series.indexer, self.series.series_id, absolute_number]
        )

    def add_custom_episode(self, season, episode, scene_absolute_number):
        self.connection.execute(
            'INSERT INTO scene_numbering (indexer, indexer_id, season, episode, scene_absolute_number) '
            'VALUES (?, ?, ?, ?, ?)',
            [self.series.indexer, self.series.series_id, season, episode, scene_absolute_number]
        )

    def select(self, query, args=None):
        return [dict(row) for row in self.connection.execute(query, args or [])]


@pytest.fixture
def sqlite_series(create_tvshow, monkeypatch, tmp_path):
    """Non-anime series matched by the parser, backed by a temporary SQLite main DB."""
    def create(is_scene=False, is_anime=False):
        series = create_tvshow(name=u'Invasion du Troisième Type', is_anime=is_anime, indexerid=102165)
        series.scene = int(is_scene)
        main_db = SQLiteMainDB(tmp_path / 'main.db', series)
        monkeypatch.setattr(helpers, 'get_show', Mock(return_value=series))
        monkeypatch.setattr(scene_exceptions, 'get_season_from_name', Mock(return_value=None))
        monkeypatch.setattr(scene_numbering.db, 'DBConnection', Mock(return_value=main_db))
        monkeypatch.setattr(scene_numbering, 'xem_refresh', Mock())
        return series, main_db

    return create


def _parse(name):
    result = NameParser().parse(name, cache_result=False, use_cache=False)
    return result.season_number, result.episode_numbers


def test_seasonless_unique_absolute_number_is_resolved(sqlite_series):
    series, main_db = sqlite_series()
    main_db.add_episode(1, 13, absolute_number=13)
    main_db.add_episode(2, 1, absolute_number=14)

    assert _parse(u'Invasion du troisième type 14 FR ovni.mp4') == (2, [1])


@pytest.mark.parametrize('name', [
    u'Invasion du troisième type 14 FR ovni.mp4',
    u'Invasion du troisième type - 14',
])
def test_seasonless_duplicate_absolute_number_is_rejected(name, sqlite_series):
    """Two episodes sharing absolute number 14: never pick one of them arbitrarily."""
    series, main_db = sqlite_series()
    main_db.add_episode(2, 2, absolute_number=14)
    main_db.add_episode(3, 4, absolute_number=14)

    with pytest.raises(InvalidNameException):
        NameParser().parse(name, cache_result=False, use_cache=False)


def test_seasonless_unknown_absolute_number_falls_back_to_season_one(sqlite_series):
    series, main_db = sqlite_series()
    main_db.add_episode(1, 1, absolute_number=1)
    main_db.add_episode(1, 2)
    main_db.add_episode(1, 3)

    assert _parse(u'Invasion du troisième type 14 FR ovni.mp4') == (1, [14])


def test_seasonless_zero_does_not_match_episodes_without_absolute_number(sqlite_series):
    """absolute_number 0 is the default for unknown values and must not resolve to an arbitrary episode."""
    series, main_db = sqlite_series()
    main_db.add_episode(2, 5)
    main_db.add_episode(3, 7)

    assert _parse(u'Invasion du troisième type 00 FR ovni.mp4') == (1, [0])


def test_seasonless_custom_absolute_mapping_with_null_season(sqlite_series):
    """A custom absolute mapping stores NULL season/episode: resolve it through its indexer absolute number."""
    series, main_db = sqlite_series()
    main_db.add_episode(2, 2, absolute_number=14)
    main_db.add_episode(2, 8, absolute_number=20)
    main_db.add_custom_absolute(absolute_number=14, scene_absolute_number=20)

    assert _parse(u'Invasion du troisième type 20 FR ovni.mp4') == (2, [2])


def test_seasonless_custom_absolute_mapping_to_unknown_episode_is_rejected(sqlite_series):
    """A custom mapping that does not lead to a library episode must not fall back to another source."""
    series, main_db = sqlite_series()
    main_db.add_episode(2, 8, absolute_number=20)
    main_db.add_custom_absolute(absolute_number=99, scene_absolute_number=20)

    with pytest.raises(InvalidNameException):
        NameParser().parse(u'Invasion du troisième type 20 FR ovni.mp4', cache_result=False, use_cache=False)


def test_seasonless_custom_episode_mapping(sqlite_series):
    series, main_db = sqlite_series()
    main_db.add_episode(3, 1, absolute_number=20)
    main_db.add_custom_episode(2, 8, scene_absolute_number=20)

    assert _parse(u'Invasion du troisième type 20 FR ovni.mp4') == (2, [8])


def test_seasonless_duplicate_custom_mappings_are_rejected(sqlite_series):
    series, main_db = sqlite_series()
    main_db.add_custom_episode(2, 8, scene_absolute_number=20)
    main_db.add_custom_episode(3, 1, scene_absolute_number=20)

    with pytest.raises(InvalidNameException):
        NameParser().parse(u'Invasion du troisième type 20 FR ovni.mp4', cache_result=False, use_cache=False)


def test_seasonless_xem_scene_absolute_number(sqlite_series):
    series, main_db = sqlite_series(is_scene=True)
    main_db.add_episode(1, 14, absolute_number=14, scene_absolute_number=0)
    main_db.add_episode(2, 3, absolute_number=15, scene_absolute_number=14)

    assert _parse(u'Invasion du troisième type 14 FR ovni.mp4') == (2, [3])


def test_seasonless_duplicate_xem_scene_absolute_number_is_rejected(sqlite_series):
    series, main_db = sqlite_series(is_scene=True)
    main_db.add_episode(2, 3, absolute_number=15, scene_absolute_number=14)
    main_db.add_episode(3, 1, absolute_number=30, scene_absolute_number=14)

    with pytest.raises(InvalidNameException):
        NameParser().parse(u'Invasion du troisième type 14 FR ovni.mp4', cache_result=False, use_cache=False)


def test_season_numbered_release_ignores_duplicate_absolute_numbers(sqlite_series):
    """Releases with an explicit season keep the season/episode lookup."""
    series, main_db = sqlite_series()
    main_db.add_episode(2, 2, absolute_number=14)
    main_db.add_episode(3, 4, absolute_number=14)

    assert _parse(u'Invasion du troisième type S03E04 FR.mp4') == (3, [4])


def test_seasonless_multi_episode_release_across_seasons_is_rejected(sqlite_series):
    series, main_db = sqlite_series()
    main_db.add_episode(1, 13, absolute_number=13)
    main_db.add_episode(2, 1, absolute_number=14)

    with pytest.raises(InvalidNameException):
        NameParser().parse(u'Invasion du troisième type 13-14 FR.mp4', cache_result=False, use_cache=False)


def test_seasonless_multi_episode_release_checks_every_number_for_ambiguity(sqlite_series):
    """An unmapped 13 must not hide an ambiguous 14 behind the season 1 fallback."""
    series, main_db = sqlite_series()
    main_db.add_episode(2, 2, absolute_number=14)
    main_db.add_episode(3, 4, absolute_number=14)

    with pytest.raises(InvalidNameException):
        NameParser().parse(u'Invasion du troisième type 13-14 FR.mp4', cache_result=False, use_cache=False)
