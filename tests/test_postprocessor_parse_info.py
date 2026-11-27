# coding=utf-8
"""Tests for medusa/post_processor.py."""
from __future__ import unicode_literals
from medusa.common import Quality
from medusa.name_parser.parser import NameParser
from medusa.post_processor import PostProcessor

import pytest


@pytest.mark.parametrize('p', [
    {  # Test file in PP folder root
        'file_path': '/media/postprocess/Show.Name.S01E01.1080p.HDTV.X264-DIMENSION.mkv',
        'nzb_name': None,
        'expected': {
            'show': 'Show Name',
            'season': 1,
            'episodes': [1],
            'quality': Quality.FULLHDTV,
            'version': -1
        }
    },
    {  # Test NZB Season pack
        'file_path': '/media/postprocess/Show.Name.S02.Season.2.1080p.BluRay.x264-PublicHD/show.name.s02e10.1080p.bluray.x264-rovers.mkv',
        'nzb_name': 'Show.Name.S02.Season.2.1080p.BluRay.x264-PublicHD',
        'expected': {
            'show': 'show name',
            'season': 2,
            'episodes': [10],
            'quality': Quality.FULLHDBLURAY,
            'version': -1
        }
    },
    {  # Test NZB single episode
        'file_path': '/media/postprocess/Show.Name.S03E13.1080p.HDTV.X264-DIMENSION/Show.Name.S03E13.1080p.HDTV.X264-DIMENSION.mkv',
        'nzb_name': 'Show.Name.S03E13.1080p.HDTV.X264-DIMENSION',
        'expected': {
            'show': 'Show Name',
            'season': 3,
            'episodes': [13],
            'quality': Quality.FULLHDTV,
            'version': -1
        }
    },
    {  # Test NZB single episode but random char name
        'file_path': '/media/postprocess/Show.Name.S12E02.The.Brain.In.The.Bot.1080p.WEB-DL.DD5.1.H.264-R2D2/161219_06.mkv',
        'nzb_name': 'Show.Name.S12E02.The.Brain.In.The.Bot.1080p.WEB-DL.DD5.1.H.264-R2D2',
        'expected': {
            'show': 'Show Name',
            'season': 12,
            'episodes': [2],
            'quality': Quality.FULLHDWEBDL,
            'version': -1
        }
    },
    {  # Test NZB multi episode
        'file_path': '/media/postprocess/Show.Name.S03E01E02.HDTV.x264-LOL/Show.Name.S03E01E02.HDTV.x264-LOL.mkv',
        'nzb_name': 'Show.Name.S03E01E02.HDTV.x264-LOL',
        'expected': {
            'show': 'Show Name',
            'season': 3,
            'episodes': [1, 2],
            'quality': Quality.SDTV,
            'version': -1
        }
    },
    {  # Quality from parent folder with source
        'file_path': 'tvs-americansDETE507/The.Americans.2013.S05E07.Hoehere.Ziele.German.DD+51.WEBDL.1080p.NetflixHD.AVC-TVS/tvs-the-americans-2013-dd51-dl-18p-nfhd-avc-507.mkv',
        'nzb_name': 'tvs-the-americans-2013-dd51-dl-18p-nfhd-avc-507.mkv',
        'expected': {
            'show': 'The Americans 2013',
            'season': 5,
            'episodes': [7],
            'quality': Quality.FULLHDWEBDL,
            'version': -1
        }
    },
    {  # Quality from parent folder with origin
        'file_path': 'tvs-americansDETE507/The.Americans.2013.S05E07.Hoehere.Ziele.German.DD+51.DL.1080p.NetflixHD.AVC-TVS/tvs-the-americans-2013-dd51-dl-18p-nfhd-avc-507.mkv',
        'nzb_name': 'tvs-the-americans-2013-dd51-dl-18p-nfhd-avc-507.mkv',
        'expected': {
            'show': 'The Americans 2013',
            'season': 5,
            'episodes': [7],
            'quality': Quality.FULLHDWEBDL,
            'version': -1
        }
    },
    {  # Quality from parent folder without source/origin
        'file_path': 'tvs-americansDETE507/The.Americans.2013.S05E07.Hoehere.Ziele.German.DD+51.DL.1080p.AVC-TVS/tvs-the-americans-2013-dd51-dl-18p-nfhd-avc-507.mkv',
        'nzb_name': 'tvs-the-americans-2013-dd51-dl-18p-nfhd-avc-507.mkv',
        'expected': {
            'show': 'The Americans 2013',
            'season': 5,
            'episodes': [7],
            'quality': Quality.FULLHDTV,
            'version': -1
        }
    }
])
def test_parse_info(p, monkeypatch, parse_method):
    """Run the test."""
    # Given
    monkeypatch.setattr(NameParser, 'parse', parse_method)
    sut = PostProcessor(file_path=p['file_path'], nzb_name=p['nzb_name'])

    # When
    show, season, episodes, quality, version, airdate = sut._parse_info()

    # Then
    assert show is not None
    assert p['expected'] == {
        'show': show.name,
        'season': season,
        'episodes': episodes,
        'quality': quality,
        'version': version,
    }


@pytest.mark.parametrize(('seasons', 'expected_season'), [
    ([1], 1),  # A single season series uses the existing season 1 fallback.
    ([1, 2], None),  # The episode stays unresolved instead of being assigned to season 1.
])
def test_find_info_production_year_release(seasons, expected_season, create_tvshow, monkeypatch):
    """A country production year does not become a season or force season 1 in post-processing."""
    import sqlite3
    from unittest.mock import Mock

    from medusa import helpers, post_processor, scene_exceptions, scene_numbering

    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.execute('CREATE TABLE tv_episodes (indexer INTEGER, showid INTEGER, season INTEGER, episode INTEGER)')
    series = create_tvshow(indexerid=99, name='Example Show')
    connection.executemany('INSERT INTO tv_episodes VALUES (?, ?, ?, ?)',
                           [(series.indexer, series.series_id, season, 4) for season in seasons])
    database = Mock()
    database.select.side_effect = lambda query, args=None: [
        dict(row) for row in connection.execute(query, args or []).fetchall()
    ]
    monkeypatch.setattr(post_processor.db, 'DBConnection', Mock(return_value=database))
    monkeypatch.setattr(helpers, 'get_show', lambda *args, **kwargs: series)
    monkeypatch.setattr(scene_exceptions, 'get_season_from_name', lambda *args, **kwargs: None)
    monkeypatch.setattr(scene_numbering, 'get_indexer_numbering', lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(scene_numbering, 'get_indexer_abs_numbering', lambda *args, **kwargs: None)
    monkeypatch.setattr(helpers, 'get_all_episodes_from_absolute_number', lambda *args, **kwargs: (None, []))

    sut = PostProcessor(file_path='/media/postprocess/Example Show - 04 - London (Fr.2022).mkv')
    found_series, season, episodes, _, _ = sut._find_info()

    assert found_series is series
    assert season == expected_season
    assert episodes == [4]
