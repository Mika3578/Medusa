# coding=utf-8
"""Tests for FixEpisodeTitleAsMultiSeason without in-place match mutation."""
from __future__ import unicode_literals

import copy

from rebulk.match import Match, Matches

from medusa.name_parser import guessit_parser as sut
from medusa.name_parser.rules.rules import FixEpisodeTitleAsMultiSeason


def test_end_to_end_xflies_trust_no_1():
    """Weak trailing season digit is folded into the episode title."""
    result = sut.guessit(
        'The.X-Flies.S09E06.Trust.No.1.x265.HEVC-Qman[UTR].mkv',
        cached=False,
    )
    assert result.get('season') == 9
    assert result.get('episode') == 6
    assert result.get('episode_title') == 'Trust No 1'


def test_existing_episode_title_uses_copies_not_mutation():
    """Existing episode_title must be replaced via remove/append copies."""
    text = 'Show.Name.S09E06.Trust.No.1.mkv'
    title = Match(0, 9, value='Show Name', name='title', input_string=text)
    season_main = Match(10, 12, value=9, name='season', input_string=text, tags=['SxxExx'])
    episode = Match(13, 15, value=6, name='episode', input_string=text, tags=['SxxExx'])
    episode_title = Match(16, 24, value='Trust No', name='episode_title', input_string=text)
    weak_season = Match(25, 26, value=1, name='season', input_string=text)
    original_title_value = episode_title.value
    original_title_id = id(episode_title)
    original_weak_id = id(weak_season)

    matches = Matches(
        [title, season_main, episode, episode_title, weak_season],
        input_string=text,
    )
    to_remove, to_append = FixEpisodeTitleAsMultiSeason().when(matches, {})

    assert weak_season in to_remove
    assert episode_title in to_remove
    fixed = next(match for match in to_append if match.name == 'episode_title')
    assert fixed.value == 'Trust No 1'
    assert id(fixed) != original_title_id
    assert episode_title.value == original_title_value
    assert id(weak_season) == original_weak_id
    assert weak_season.name == 'season'
    assert weak_season.value == 1


def test_missing_episode_title_appends_copy_instead_of_mutating_season():
    """Weak season becomes a new episode_title copy; original season stays intact."""
    text = 'Show.Name.S01E02.3.mkv'
    title = Match(0, 9, value='Show Name', name='title', input_string=text)
    season_main = Match(10, 12, value=1, name='season', input_string=text, tags=['SxxExx'])
    episode = Match(13, 15, value=2, name='episode', input_string=text, tags=['SxxExx'])
    weak_season = Match(16, 17, value=3, name='season', input_string=text)
    original = copy.copy(weak_season)

    matches = Matches([title, season_main, episode, weak_season], input_string=text)
    to_remove, to_append = FixEpisodeTitleAsMultiSeason().when(matches, {})

    assert weak_season in to_remove
    assert weak_season.name == 'season'
    assert weak_season.value == original.value
    new_title = next(match for match in to_append if match.name == 'episode_title')
    assert new_title.value == '3'
    assert id(new_title) != id(weak_season)


def test_anime_context_skips_rule():
    """Anime shows must not trigger the multi-season title rewrite."""
    text = 'Show.Name.S01E02.3.mkv'
    matches = Matches([
        Match(0, 9, value='Show Name', name='title', input_string=text),
        Match(10, 12, value=1, name='season', input_string=text, tags=['SxxExx']),
        Match(13, 15, value=2, name='episode', input_string=text, tags=['SxxExx']),
        Match(16, 17, value=3, name='season', input_string=text),
    ], input_string=text)

    assert FixEpisodeTitleAsMultiSeason().when(matches, {'show_type': 'anime'}) is None


def test_strong_second_sxxexx_is_not_removed():
    """A real second SxxExx season must not be treated as a weak title digit."""
    text = 'Show.Name.S01E02.S02E03.mkv'
    season1 = Match(10, 12, value=1, name='season', input_string=text, tags=['SxxExx'])
    episode1 = Match(13, 15, value=2, name='episode', input_string=text, tags=['SxxExx'])
    season2 = Match(16, 18, value=2, name='season', input_string=text, tags=['SxxExx'])
    episode2 = Match(19, 21, value=3, name='episode', input_string=text, tags=['SxxExx'])
    # Link second season/episode as siblings under same parent initiator shape
    parent = Match(16, 21, value='S02E03', name='episode', input_string=text)
    season2.parent = parent
    episode2.parent = parent

    matches = Matches([
        Match(0, 9, value='Show Name', name='title', input_string=text),
        season1, episode1, season2, episode2,
    ], input_string=text)

    # next_episode after season2 exists -> rule returns None
    assert FixEpisodeTitleAsMultiSeason().when(matches, {}) is None
