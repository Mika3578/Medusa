# coding=utf-8
"""Tests for ExtractSeasonFromTitleSeasonWord GuessIt 4 adaptation."""
from __future__ import unicode_literals

from rebulk.match import Match, Matches

from medusa.name_parser import guessit_parser as sut
from medusa.name_parser.rules.rules import ExtractSeasonFromTitleSeasonWord


def _episode_with_initiator(start, end, value, initiator_value, initiator_start=None, initiator_end=None,
                            input_string=None):
    """Build an episode Match whose initiator carries an Episode token."""
    initiator_start = start if initiator_start is None else initiator_start
    initiator_end = end if initiator_end is None else initiator_end
    initiator = Match(
        initiator_start,
        initiator_end,
        value=initiator_value,
        name='episode',
        input_string=input_string,
    )
    return Match(
        start,
        end,
        value=value,
        name='episode',
        parent=initiator,
        input_string=input_string,
    )


def test_rule_requires_unique_episode_token_initiator():
    """Multiple Episode-token episodes must abort the rewrite."""
    text = 'Ajin Season 2 Episode 13 Episode 14'
    title = Match(0, 12, value='Ajin Season 2', name='title', input_string=text)
    episode_a = _episode_with_initiator(13, 23, 13, 'Episode 13', 13, 23, text)
    episode_b = _episode_with_initiator(24, 34, 14, 'Episode 14', 24, 34, text)
    matches = Matches([title, episode_a, episode_b], input_string=text)

    assert ExtractSeasonFromTitleSeasonWord().when(matches, {}) is None


def test_rule_removes_only_absolute_episode_for_same_initiator():
    """Unrelated absolute_episode matches must be preserved."""
    text = 'Ajin Season 2 Episode 13 extra 99'
    title = Match(0, 12, value='Ajin Season 2', name='title', input_string=text)
    episode = _episode_with_initiator(13, 23, 13, 'Episode 13', 13, 23, text)
    same_abs = Match(21, 23, value=13, name='absolute_episode', parent=episode.initiator, input_string=text)
    other_init = Match(30, 32, value='99', name='episode', input_string=text)
    other_abs = Match(30, 32, value=99, name='absolute_episode', parent=other_init, input_string=text)
    matches = Matches([title, episode, same_abs, other_abs], input_string=text)

    to_remove, to_append = ExtractSeasonFromTitleSeasonWord().when(matches, {})
    removed_absolute = [match for match in to_remove if match.name == 'absolute_episode']
    assert removed_absolute == [same_abs]
    assert other_abs not in to_remove

    seasons = [match for match in to_append if match.name == 'season']
    assert len(seasons) == 1
    assert seasons[0].value == 2


def test_rule_season_span_covers_digits_only():
    """Season match span must cover only the captured season digits."""
    text = 'Ajin.Season.2.Episode.13'
    title = Match(0, 13, value='Ajin Season 2', name='title', input_string=text)
    episode = _episode_with_initiator(14, 24, 13, 'Episode 13', 14, 24, text)
    matches = Matches([title, episode], input_string=text)

    _to_remove, to_append = ExtractSeasonFromTitleSeasonWord().when(matches, {})
    season = next(match for match in to_append if match.name == 'season')

    assert season.value == 2
    assert season.start < season.end
    assert text[season.start:season.end] == '2'
    assert season.start == text.index('2')
    assert season.end == season.start + 1


def test_guessit_ajin_season_episode_pattern():
    """End-to-end: Season+Episode release keeps title/season/episode identity."""
    result = sut.guessit(
        '[Ajin2.com].Ajin.Season.2.Episode.13.[End].[720p].[Subbed]',
        cached=False,
    )
    assert result.get('title') == 'Ajin'
    assert result.get('season') == 2
    assert result.get('episode') == 13
