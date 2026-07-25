# coding=utf-8
"""Regression and coverage tests for monthly month/year release parsing."""
from __future__ import unicode_literals

from datetime import date

import pytest

import medusa.name_parser.guessit_parser as guessit_parser
from medusa import app


@pytest.fixture(autouse=True)
def _empty_show_list(monkeypatch):
    monkeypatch.setattr(app, 'showList', [])


MONTHLY_NAME_YEAR_CASES = [
    # French
    ('Le.Journal.Du.Hard.Janvier.2019.FRENCH.720p.HDTV.x264-SH0W', date(2019, 1, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Fevrier.2018.FRENCH.720p.HDTV.x264-SH0W', date(2018, 2, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Mars.2018.FRENCH.720p.HDTV.x264-ANALPLUX', date(2018, 3, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Avril.2018.FRENCH.720p.HDTV.x264-SH0W', date(2018, 4, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Mai.2016.FRENCH.HDTV.x264-SH0W', date(2016, 5, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Juin.2018.FRENCH.720p.HDTV.x264-SH0W', date(2018, 6, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Juillet.2017.FRENCH.720p.HDTV.x264-SH0W', date(2017, 7, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Aout.2017.FRENCH.720p.HDTV.x264-SH0W', date(2017, 8, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Septembre.2018.FRENCH.720p.HDTV.x264-SH0W', date(2018, 9, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Octobre.2018.FRENCH.720p.HDTV.x264-SH0W', date(2018, 10, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Novembre.2019.FRENCH.720p.HDTV.x264-SH0W', date(2019, 11, 1), 'Le Journal Du Hard'),
    ('Le.Journal.Du.Hard.Decembre.2018.FRENCH.720p.HDTV.x264-SH0W', date(2018, 12, 1), 'Le Journal Du Hard'),
    # English
    ('Show.Name.January.2018.HDTV.x264-GROUP', date(2018, 1, 1), 'Show Name'),
    ('Show.Name.February.2018.HDTV.x264-GROUP', date(2018, 2, 1), 'Show Name'),
    ('Show.Name.March.2018.HDTV.x264-GROUP', date(2018, 3, 1), 'Show Name'),
    ('Show.Name.April.2018.HDTV.x264-GROUP', date(2018, 4, 1), 'Show Name'),
    ('Show.Name.May.2018.HDTV.x264-GROUP', date(2018, 5, 1), 'Show Name'),
    ('Show.Name.June.2018.HDTV.x264-GROUP', date(2018, 6, 1), 'Show Name'),
    ('Show.Name.July.2018.HDTV.x264-GROUP', date(2018, 7, 1), 'Show Name'),
    ('Show.Name.August.2017.HDTV.x264-GROUP', date(2017, 8, 1), 'Show Name'),
    ('Show.Name.September.2018.HDTV.x264-GROUP', date(2018, 9, 1), 'Show Name'),
    ('Show.Name.October.2018.HDTV.x264-GROUP', date(2018, 10, 1), 'Show Name'),
    ('Show.Name.November.2018.HDTV.x264-GROUP', date(2018, 11, 1), 'Show Name'),
    ('Show.Name.December.2018.HDTV.x264-GROUP', date(2018, 12, 1), 'Show Name'),
    ('Monthly.Show.Sep.2020.720p.WEB.h264-GROUP', date(2020, 9, 1), 'Monthly Show'),
    ('Show.Name.Oct.2019.720p.HDTV.x264-GROUP', date(2019, 10, 1), 'Show Name'),
    # Other Medusa languages
    ('Show.Name.Mayo.2016.HDTV.x264-GROUP', date(2016, 5, 1), 'Show Name'),  # es
    ('Show.Name.Maggio.2016.HDTV.x264-GROUP', date(2016, 5, 1), 'Show Name'),  # it
    ('Show.Name.Mei.2016.HDTV.x264-GROUP', date(2016, 5, 1), 'Show Name'),  # nl
    ('Show.Name.Maio.2016.HDTV.x264-GROUP', date(2016, 5, 1), 'Show Name'),  # pt
    ('Show.Name.Maj.2016.HDTV.x264-GROUP', date(2016, 5, 1), 'Show Name'),  # pl/sv/da
    ('Show.Name.Mai.2016.GERMAN.HDTV.x264-GROUP', date(2016, 5, 1), 'Show Name'),  # de
    ('Show.Name.Agustos.2018.HDTV.x264-GROUP', date(2018, 8, 1), 'Show Name'),  # tr
    ('Show.Name.Yanvar.2019.HDTV.x264-GROUP', date(2019, 1, 1), 'Show Name'),  # ru
    ('Show.Name.Kesakuu.2020.HDTV.x264-GROUP', date(2020, 6, 1), 'Show Name'),  # fi
    ('Show.Name.Desember.2021.HDTV.x264-GROUP', date(2021, 12, 1), 'Show Name'),  # no
    ('Show.Name.Marts.2017.HDTV.x264-GROUP', date(2017, 3, 1), 'Show Name'),  # da
    ('Show.Name.Augusti.2018.HDTV.x264-GROUP', date(2018, 8, 1), 'Show Name'),  # sv
    ('Show.Name.Styczen.2019.HDTV.x264-GROUP', date(2019, 1, 1), 'Show Name'),  # pl
    ('Show.Name.Sijecanj.2020.HDTV.x264-GROUP', date(2020, 1, 1), 'Show Name'),  # hr
    ('Show.Name.Ianuarie.2018.HDTV.x264-GROUP', date(2018, 1, 1), 'Show Name'),  # ro
    # Space-separated + JDH tag (Journal du Hard scene packs)
    ('Le Journal du Hard Mars 2012 JDH 03 2012 avi', date(2012, 3, 1), 'Le Journal du Hard'),
    ('Le Journal du Hard Fevrier 2012 JDH 02 2012 avi', date(2012, 2, 1), 'Le Journal du Hard'),
    ('Le Journal du Hard Juillet 2012 JDH 07 2012 avi', date(2012, 7, 1), 'Le Journal du Hard'),
    ('Le Journal du Hard Avril 2012 JDH 04 2012 avi', date(2012, 4, 1), 'Le Journal du Hard'),
    ('Le Journal Du Hard Novembre 2012 FRENCH PDTV x264 ANALPLUX', date(2012, 11, 1), 'Le Journal Du Hard'),
    ('Le Journal Du Hard Fevrier 2011 FRENCH 720p HDTV x264 RAWHD', date(2011, 2, 1), 'Le Journal Du Hard'),
    ('Le Journal Du Hard Septembre 2012 FRENCH HDTV x264 ANALPLUX', date(2012, 9, 1), 'Le Journal Du Hard'),
    ('Le Journal Du Hard Decembre 2012 FRENCH PDTV x264 ANALPLUX', date(2012, 12, 1), 'Le Journal Du Hard'),
    (
        'Le Journal du Hard Juin 2023 erotic bts french lingerie lettowv7 '
        'blonde brunette click on my channel name Lettowv7 to see more mp4',
        date(2023, 6, 1),
        'Le Journal du Hard',
    ),
]


MONTHLY_NUMERIC_CASES = [
    # 2-digit month
    ('Le.Journal.Du.Hard.08.1998', date(1998, 8, 1)),
    ('Le.journal.du.hard.07.2024', date(2024, 7, 1)),
    ('Le.journal.du.hard.10.2024', date(2024, 10, 1)),
    ('Show.Name.05.2016.HDTV.x264-GROUP', date(2016, 5, 1)),
    ('Show.Name.2016.05', date(2016, 5, 1)),
    ('planet3-le.journal.du.hard.2011.01.french.720p.hdtv', date(2011, 1, 1)),
    ('Show.Name.2016.12', date(2016, 12, 1)),
    ('Show.Name.01.2000', date(2000, 1, 1)),
    ('Show.Name.09.2024.HDTV.x264-GROUP', date(2024, 9, 1)),
    # 1-digit month
    ('Show.Name.5.2016.HDTV.x264-GROUP', date(2016, 5, 1)),
    ('Show.Name.2016.5', date(2016, 5, 1)),
    ('Show.Name.1.2024', date(2024, 1, 1)),
    ('Show.Name.2024.1', date(2024, 1, 1)),
    ('Show.Name.9.2018.720p.HDTV.x264-GROUP', date(2018, 9, 1)),
    ('Show.Name.2018.9.HDTV.x264-GROUP', date(2018, 9, 1)),
]


FULL_DATE_CASES = [
    # 2-digit month and day
    ('Le.Journal.Du.Hard.2016.01.03.FRENCH.720p.HDTV.x264-SH0W', date(2016, 1, 3)),
    ('Show.Name.2010.11.23.HDTV.720p.x264-Group', date(2010, 11, 23)),
    ('Show Name - 2010.11.23 - Episode Name', date(2010, 11, 23)),
    ('Show.Name.2016.05.07.HDTV.x264-GROUP', date(2016, 5, 7)),
    ('Show.Name.07.05.2016.HDTV.x264-GROUP', date(2016, 5, 7)),
    # 1-digit month and/or day
    ('Show.Name.2016.5.7.HDTV.x264-GROUP', date(2016, 5, 7)),
    ('Show.Name.2016.5.07.HDTV.x264-GROUP', date(2016, 5, 7)),
    ('Show.Name.2016.05.7.HDTV.x264-GROUP', date(2016, 5, 7)),
    ('Show.Name.7.5.2016.HDTV.x264-GROUP', date(2016, 5, 7)),
    ('Show.Name.2016.1.3.HDTV.x264-GROUP', date(2016, 1, 3)),
    ('Show.Name.2016.01.3.HDTV.x264-GROUP', date(2016, 1, 3)),
    ('Show.Name.2016.1.03.HDTV.x264-GROUP', date(2016, 1, 3)),
]


# Real-world YggReborn releases using dash (MM-YYYY), often inside parentheses.
# guessit mis-parses these as SxxExx with season == year; they must resolve to
# a month-precision date instead.
DASH_MONTH_YEAR_CASES = [
    ('[CANAL+] Le Journal du Hard (02-2021) TVRIP/1080p/AVC', date(2021, 2, 1), 'Le Journal du Hard'),
    ('[CANAL+] Le Journal du Hard (03-2021) TVRIP/1080p/AVC', date(2021, 3, 1), 'Le Journal du Hard'),
    ('[CANAL+] Le Journal du Hard (06-2021) TVRIP/1080p/AVC', date(2021, 6, 1), 'Le Journal du Hard'),
    ('[CANAL+] Le Journal du Hard (01-2023) TVRIP/1080P/MP4', date(2023, 1, 1), 'Le Journal du Hard'),
    ('[CANAL+] Le Journal du Hard (10-2022) TVRIP/1080P/MP4', date(2022, 10, 1), 'Le Journal du Hard'),
    ('[CANAL+] Le Journal du Hard (07-2023) WEB-DL/720P/MP4', date(2023, 7, 1), 'Le Journal du Hard'),
    ('[CANAL+] Le Journal du Hard 07-2025 FRENCH 1080p WEB x264', date(2025, 7, 1), 'Le Journal du Hard'),
    # Parenthesized month name + year
    ('Le Journal du Hard (Avril-2021)', date(2021, 4, 1), 'Le Journal du Hard'),
    # Two-digit year (dash only)
    ('JDH-01-24', date(2024, 1, 1), 'JDH'),
    ('JDH-03-24', date(2024, 3, 1), 'JDH'),
    ('JDH-04-24-720p', date(2024, 4, 1), 'JDH'),
    ('Le journal du hard 09-24', date(2024, 9, 1), 'Le journal du hard'),
    # Compact JDH tags: title must not swallow the month digits
    ('JDH04-2022', date(2022, 4, 1), 'JDH'),
    ('JDH09-21', date(2021, 9, 1), 'JDH'),
    ('JDH122022', date(2022, 12, 1), 'JDH'),
    # Full post-process path (folder + file both contain MM-YYYY)
    (
        r'\\server\downloads\tv\JDH\JDH-01-2022\JDH-01-2022.mp4',
        date(2022, 1, 1),
        'JDH',
    ),
    # Directory components must not leak into the title
    (
        r'\\server\downloads\tv\JDH\Journal du Hard Novembre 2020\Journal du Hard Novembre 2020.mp4',
        date(2020, 11, 1),
        'Journal du Hard',
    ),
    # Leading bracketed release tags must not leak into the title
    ('[CANAL+] Journal du Hard - Juin 2021.mkv', date(2021, 6, 1), 'Journal du Hard'),
    ('[CANAL+] Journal du Hard Janvier 2021.mp4', date(2021, 1, 1), 'Journal du Hard'),
    ('[JDH] Le journal du hard - Juillet 2022 WEBrip 2160p x265 AAC', date(2022, 7, 1), 'Le journal du hard'),
    ('[JDH].Le.journal.du.hard.2022.07.Juillet.2022.4KRip.H265.AAC', date(2022, 7, 1), 'Le journal du hard'),
    # A season folder must not turn the file's month into an episode number
    (
        r'M:\media\tv\Le journal du hard (1991)\Le journal du hard S35\Le journal du hard 01-2026.mkv',
        date(2026, 1, 1),
        'Le journal du hard',
    ),
    (
        r'M:\media\tv\Le journal du hard (1991)\Le journal du hard S35\Le journal du hard Janvier 2026.mkv',
        date(2026, 1, 1),
        'Le journal du hard',
    ),
    (
        r'M:\media\tv\Le journal du hard (1991)\Le journal du hard S33\JDH-04-24-720p',
        date(2024, 4, 1),
        'Le journal du hard',
    ),
    (
        r'M:\media\tv\Le journal du hard (1991)\Le journal du hard S32\JDH-03-23',
        date(2023, 3, 1),
        'Le journal du hard',
    ),
]


STANDARD_SXXEXX_CASES = [
    ('Show.Name.S01E05.HDTV.x264-GROUP', 1, 5),
    ('Show.Name.S03E08.REPACK.PROPER.HDTV.x264-GROUP', 3, 8),
    ('The.100.S01E01.720p.HDTV.x264-GROUP', 1, 1),
    ('Show.Name.S02E10.720p.BluRay.x264-GROUP', 2, 10),
]


@pytest.mark.parametrize('release_name,expected_date,expected_title', MONTHLY_NAME_YEAR_CASES)
def test_monthly_month_name_year_releases(release_name, expected_date, expected_title):
    result = guessit_parser.guessit(release_name, cached=False)
    assert result.get('date') == expected_date
    assert result.get('date_precision') == 'month'
    assert result.get('title') == expected_title
    assert 'season' not in result
    assert 'episode' not in result


@pytest.mark.parametrize('release_name,expected_date', MONTHLY_NUMERIC_CASES)
def test_monthly_numeric_month_year_releases(release_name, expected_date):
    result = guessit_parser.guessit(release_name, cached=False)
    assert result.get('date') == expected_date
    assert result.get('date_precision') == 'month'
    assert 'season' not in result
    assert 'episode' not in result


@pytest.mark.parametrize('release_name,expected_date,expected_title', DASH_MONTH_YEAR_CASES)
def test_dash_month_year_releases(release_name, expected_date, expected_title):
    result = guessit_parser.guessit(release_name, cached=False)
    assert result.get('date') == expected_date
    assert result.get('date_precision') == 'month'
    if expected_title is not None:
        assert result.get('title') == expected_title
    assert 'season' not in result
    assert 'episode' not in result


@pytest.mark.parametrize('release_name,expected_date', FULL_DATE_CASES)
def test_full_air_date_releases_digit_widths(release_name, expected_date):
    result = guessit_parser.guessit(release_name, cached=False)
    assert result.get('date') == expected_date
    assert result.get('date_precision') is None


@pytest.mark.parametrize('release_name,season,episode', STANDARD_SXXEXX_CASES)
def test_standard_sxxexx_not_converted_to_month_year(release_name, season, episode):
    result = guessit_parser.guessit(release_name, cached=False)
    assert result.get('date') is None
    assert result.get('season') == season
    assert result.get('episode') == episode


@pytest.mark.parametrize('release_name,season,episode', [
    (r'M:\media\tv\Show Name\Season 03\Show.Name.S03E05.1080p.mkv', 3, 5),
    (r'M:\media\tv\Show (2011)\Season 01\Show.Name.S01E02.mkv', 1, 2),
])
def test_sxxexx_in_library_path_not_converted(release_name, season, episode):
    result = guessit_parser.guessit(release_name, cached=False)
    assert result.get('date') is None
    assert result.get('season') == season
    assert result.get('episode') == episode


def test_year_as_season_sxxexx_not_converted():
    result = guessit_parser.guessit('Show.Name.S2016E08.HDTV.x264-GROUP', cached=False)
    assert result.get('date') is None
    assert result.get('season') == 2016
    assert result.get('episode') == 8


@pytest.mark.parametrize('release_name', [
    'Show.Name.12.13.HDTV.x264-GROUP',
    'Show.Name.09.10.HDTV.x264-GROUP',
])
def test_weak_episode_pairs_not_converted_to_month_year(release_name):
    result = guessit_parser.guessit(release_name, cached=False)
    assert result.get('date') is None
    assert result.get('episode') is not None


@pytest.mark.parametrize('release_name', [
    'Show.Name.-.07.(2016).[RH].[English.Dubbed][WEBRip]..[HD.1080p]',
    'Show!.Name.2.-.10.(2016).[HorribleSubs][WEBRip]..[HD.720p]',
    'VA_-_Redux_presents_The_Uplifting_Selection_Vol_1-2019-(RDXSEL026)-WEB-2019-ZzZz',
    'Show.Name.E02.2010',
])
def test_anime_volume_and_exx_year_not_converted_to_month_year(release_name):
    result = guessit_parser.guessit(release_name, cached=False)
    assert result.get('date') is None


@pytest.mark.parametrize('release_name', [
    # Truncated month tokens from bad display/encoding — ignored on purpose
    'Le Journal du Hard Ao 2022 erotic bts french mp4',
    'Le Journal du Hard cembre 2023 erotic bts french mp4',
    'Le Journal du Hard vrier 2024 erotic bts french mp4',
])
def test_truncated_display_month_glitches_are_ignored(release_name):
    result = guessit_parser.guessit(release_name, cached=False)
    assert result.get('date') is None
    assert result.get('date_precision') is None


def test_month_precision_matches_first_saturday_airdate(monkeypatch, create_tvshow):
    """Mai.2016 must match the episode airing on the first Saturday, not day 1."""
    from medusa.name_parser.parser import NameParser, ParseResult

    series = create_tvshow(name='Le Journal Du Hard', lang='fr')
    series.air_by_date = 1

    # 2016-05-01 was a Sunday; first Saturday of May 2016 is 2016-05-07
    first_saturday = date(2016, 5, 7)

    class FakeDB(object):
        def select(self, query, args=None):
            args = args or []
            # Exact day lookup for placeholder 2016-05-01 -> miss
            if 'airdate = ?' in query and 'airdate >=' not in query:
                return []
            # Month range lookup
            if 'airdate >= ?' in query and 'airdate < ?' in query:
                start, end = args[2], args[3]
                if start <= first_saturday.toordinal() < end:
                    return [{'season': 2016, 'episode': 5}]
            return []

    monkeypatch.setattr('medusa.name_parser.parser.db.DBConnection', lambda: FakeDB())

    guess = guessit_parser.guessit(
        'Le.Journal.Du.Hard.Mai.2016.FRENCH.HDTV.x264-SH0W',
        cached=False,
    )
    assert guess.get('date_precision') == 'month'
    assert guess.get('date') == date(2016, 5, 1)

    parser = NameParser(series=series)
    result = ParseResult(
        guess,
        series_name='Le Journal Du Hard',
        air_date=guess.get('date'),
        date_precision=guess.get('date_precision'),
        original_name='Le.Journal.Du.Hard.Mai.2016.FRENCH.HDTV.x264-SH0W',
    )
    result.series = series
    episodes, seasons = parser._parse_air_by_date(result)
    assert seasons == [2016]
    assert episodes == [5]
