# coding=utf-8
"""Tests for medusa/test_list_associated_files.py."""
from __future__ import unicode_literals

from medusa.name_parser.parser import NameParser

import guessit
import pytest


@pytest.mark.parametrize(('filename', 'episode', 'season'), [
    ('Example.Show.-.01.-.Harbour.(Fr.2021)_Channel.2022-03-24.mkv', 1, None),
    ('Example.Show.-.04.-.London.(Fr.2022)_Channel.2022-03-31.mkv', 4, None),
    ('Example.Show.S2022E04.London.(Fr.2022).mkv', 4, 2022),
])
def test_production_year_is_not_an_implicit_season(filename, episode, season):
    """Preserve explicitly numbered seasons and discard misidentified production years."""
    from medusa.name_parser.guessit_parser import guessit as parse_filename

    result = NameParser().to_parse_result(filename, parse_filename(filename, cached=False))
    assert result.season_number == season
    assert result.episode_numbers == [episode]


def test_production_year_match_stays_within_the_release_filename():
    """Ignore annotations in directory names and tolerate long separators."""
    guess = {'title': 'Example Show', 'season': 2022, 'episode': 4, 'year': 2022}
    parser = NameParser()
    filename = 'Example Show - 04 - London' + ' ' * 10000 + '(Fr.2022).mkv'
    folder = 'Example Show - 04 - London (Fr.2022)'

    assert parser.to_parse_result(filename, guess).season_number is None
    assert parser.to_parse_result(folder + '/Example Show S2022E04.mkv', guess).season_number == 2022


@pytest.mark.parametrize(('annotated', 'plain'), [
    ('Example Show - 14 - London (Fr.2022).mkv', 'Example Show - 14 - London.mkv'),
    ('Example.Show.-.04.-.London.(Fr.2022)_Channel.2022-03-31.mkv', 'Example.Show.-.04.-.London_Channel.2022-03-31.mkv'),
])
def test_production_year_release_parses_like_unannotated_release(annotated, plain):
    """Keep the absolute numbering guessit assigns to the same release without the annotation."""
    from medusa.name_parser.guessit_parser import guessit as parse_filename

    parser = NameParser()
    expected = parser.to_parse_result(plain, parse_filename(plain, cached=False))
    actual = parser.to_parse_result(annotated, parse_filename(annotated, cached=False))

    assert expected.season_number is None
    assert actual.season_number == expected.season_number
    assert actual.episode_numbers == expected.episode_numbers
    assert actual.ab_episode_numbers == expected.ab_episode_numbers


@pytest.mark.parametrize(('name', 'season', 'episodes'), [
    # The production year must not fall back to an assumed season 1.
    ('Example Show - 04 - London (Fr.2022).mkv', None, [4]),
    ('Example Show (Fr.2022)/Example Show - 04 - London (Fr.2022).mkv', None, [4]),
    # Explicit numbering is preserved.
    ('Example.Show.S2022E04.London.(Fr.2022).mkv', 2022, [4]),
    ('Example.Show.S02E04.London.(Fr.2022).mkv', 2, [4]),
    ('Example Show - 04 - London (Fr.2022)/Example.Show.S2022E04.mkv', 2022, [4]),
])
def test_production_year_full_parse_with_known_series(name, season, episodes, create_tvshow, monkeypatch):
    """Parse production-year releases end to end without assuming season 1."""
    from medusa import helpers, scene_exceptions, scene_numbering

    series = create_tvshow(indexerid=99, name='Example Show')
    monkeypatch.setattr(helpers, 'get_show', lambda *args, **kwargs: series)
    monkeypatch.setattr(scene_exceptions, 'get_season_from_name', lambda *args, **kwargs: None)
    monkeypatch.setattr(scene_numbering, 'get_indexer_numbering', lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(scene_numbering, 'get_indexer_abs_numbering', lambda *args, **kwargs: None)

    result = NameParser().parse(name, cache_result=False, use_cache=False)

    assert result.series is series
    assert result.season_number == season
    assert result.episode_numbers == episodes


def test_production_year_absolute_number_maps_anime_episode(create_tvshow, monkeypatch):
    """The dash-delimited number still resolves through the absolute numbering of an anime series."""
    from medusa import helpers, scene_exceptions, scene_numbering

    series = create_tvshow(indexerid=99, name='Example Show', anime=1)
    monkeypatch.setattr(helpers, 'get_show', lambda *args, **kwargs: series)
    monkeypatch.setattr(scene_exceptions, 'get_season_from_name', lambda *args, **kwargs: None)
    monkeypatch.setattr(scene_numbering, 'get_indexer_numbering', lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(scene_numbering, 'get_indexer_abs_numbering', lambda *args, **kwargs: None)
    monkeypatch.setattr(helpers, 'get_all_episodes_from_absolute_number',
                        lambda show, numbers: (2, [1]) if numbers == [14] else (None, []))

    for parse_method in (None, 'anime'):
        result = NameParser(parse_method=parse_method).parse(
            'Example Show - 14 - London (Fr.2022).mkv', cache_result=False, use_cache=False)
        assert (result.season_number, result.episode_numbers, result.ab_episode_numbers) == (2, [1], [14])


@pytest.mark.parametrize('p', [
    # The regular Show uses xem data. To map scene S06E29 to indexer S06E28
    {
        'name': u'Regular.Show.S06E29.Dumped.at.the.Altar.720p.HDTV.x264-W4F',
        'indexer_id': 1,
        'indexer': 188401,
        'mocks': [
            ('medusa.scene_numbering.get_indexer_numbering', (6, 28))
        ],
        'series_info': {
            'name': u'Regular Show',
            'is_scene': True
        },
        'expected': ([28], [6], []),
    },
    {
        'name': u'Inside.West.Coast.Customs.S06E04.720p.WEB.x264-TBS',
        'indexer_id': 1,
        'indexer': 307007,
        'mocks': [
            ('medusa.scene_numbering.get_indexer_numbering', (8, 4))
        ],
        'series_info': {
            'name': u'Inside West Coast Customs',
            'is_scene': True
        },
        'expected': ([4], [8], []),
    },
    {
        'name': u'The.100.S04E13.1080p.BluRay.x264-SPRINTER-Scrambled',
        'indexer_id': 1,
        'indexer': 307007,
        'mocks': [
            ('medusa.scene_numbering.get_indexer_numbering', (None, None))
        ],
        'series_info': {
            'name': u'The 100',
            'is_scene': False
        },
        'expected': ([13], [4], []),
    },
    {
        'name': u'American.Dad.S14E02.XviD-AFG',
        'indexer_id': 1,
        'indexer': 73141,
        'mocks': [
            ('medusa.scene_numbering.get_indexer_numbering', (15, 1))
        ],
        'series_info': {
            'name': u'American Dad',
            'is_scene': True
        },
        'expected': ([1], [15], []),
    },
    {
        'name': u'Universe.Possible.Worlds.S01E12.HDTV.x264-aAF',
        'indexer_id': 1,
        'indexer': 260586,
        'mocks': [
            ('medusa.scene_exceptions.get_season_from_name', 2),
            ('medusa.scene_numbering.get_indexer_numbering', (2, 12))
        ],
        'series_info': {
            'name': u'Universe (2014)',
            'is_scene': False
        },
        'expected': ([12], [2], []),
    },
    {
        'name': u'Universe.Possible.Worlds.S01E12.HDTV.x264-aAF',
        'indexer_id': 1,
        'indexer': 260586,
        'mocks': [
            ('medusa.scene_exceptions.get_season_from_name', 2),
            ('medusa.scene_numbering.get_indexer_numbering', (2, 12))
        ],
        'series_info': {
            'name': u'Universe (2014)',
            'is_scene': True
        },
        'expected': ([12], [2], []),
    },
])
def test_series_parsing(p, create_tvshow, monkeypatch_function_return):

    monkeypatch_function_return(p['mocks'])

    parser = NameParser()
    guess = guessit.guessit(p['name'])
    result = parser.to_parse_result(p['name'], guess)

    # confirm passed in show object indexer id matches result show object indexer id
    result.series = create_tvshow(name=p['series_info']['name'])
    result.series.scene = p['series_info']['is_scene']

    actual = parser._parse_series(result)

    expected = p['expected']

    assert expected == actual
