# coding=utf-8
"""Tests for RestoreSeasonFromXPattern span restoration."""
from __future__ import unicode_literals

from rebulk.match import Match, Matches

from medusa.name_parser import guessit_parser as sut
from medusa.name_parser.rules.rules import RestoreSeasonFromXPattern


def test_restore_season_span_covers_digits_only():
    """Season/episode spans must cover only the NNxNN digit groups."""
    text = 'Rugrats - 01x02 - Episode title.mkv'
    idx = text.index('01x02')
    initiator = Match(idx, idx + 5, value='01x02', name='episode', input_string=text)
    # Simulate GuessIt keeping a single episode child spanning the whole initiator.
    episode = Match(
        idx, idx + 5, value=2, name='episode', parent=initiator,
        input_string=text, tags=['SxxExx'],
    )
    matches = Matches([
        Match(0, 7, value='Rugrats', name='title', input_string=text),
        episode,
    ], input_string=text)

    to_remove, to_append = RestoreSeasonFromXPattern().when(matches, {})
    season = next(match for match in to_append if match.name == 'season')
    fixed_episode = next(match for match in to_append if match.name == 'episode')

    assert season.value == 1
    assert fixed_episode.value == 2
    assert season.start < season.end
    assert fixed_episode.start < fixed_episode.end
    assert text[season.start:season.end] == '01'
    assert text[fixed_episode.start:fixed_episode.end] == '02'
    assert episode in to_remove


def test_restore_season_span_with_windows_path():
    """Absolute coordinates must remain correct inside a Windows path."""
    text = r'C:\TV\Rugrats Season 1\Rugrats - 01x02 - Episode title.mkv'
    idx = text.index('01x02')
    initiator = Match(idx, idx + 5, value='01x02', raw='01x02', name='episode', input_string=text)
    episode = Match(
        idx, idx + 5, value=2, name='episode', parent=initiator,
        input_string=text, tags=['SxxExx'],
    )
    matches = Matches([episode], input_string=text)

    _to_remove, to_append = RestoreSeasonFromXPattern().when(matches, {})
    season = next(match for match in to_append if match.name == 'season')
    fixed_episode = next(match for match in to_append if match.name == 'episode')

    assert season.value == 1
    assert fixed_episode.value == 2
    assert text[season.start:season.end] == '01'
    assert text[fixed_episode.start:fixed_episode.end] == '02'


def test_restore_season_end_to_end_guessit():
    """End-to-end parse keeps season/episode identity for Rugrats NNxNN."""
    result = sut.guessit('Rugrats - 01x02 - Episode title.mkv', cached=False)
    assert result.get('title') == 'Rugrats'
    assert result.get('season') == 1
    assert result.get('episode') == 2
