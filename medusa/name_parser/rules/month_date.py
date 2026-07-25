# coding=utf-8
"""Rules to create air dates from month/year release patterns.

Handles scene releases for monthly shows that use a month name or month number
with a year instead of a full YYYY.MM.DD date, for example:

  Show.Name.Mai.2016...
  Show.Name.August.2017...
  Show.Name.08.1998
  Show.Name.10.2024
  Show.Name.2011.01...

Day is set to 1 only as a technical placeholder when the release has no day.
That is NOT the broadcast day (e.g. Le Journal du Hard airs on the first
Saturday of the month). Matching must resolve the real episode by year+month.
"""
from __future__ import unicode_literals

import copy
import re
from datetime import date

from medusa.helper.month_names import MONTH_NAME_TO_NUMBER, first_date_of_month, month_from_name

from rebulk.match import Match
from rebulk.processors import POST_PROCESS
from rebulk.rules import AppendMatch, Consequence, Rule


class SafeRemoveMatch(Consequence):
    """Like RemoveMatch, but tolerate rebulk dict/list inconsistency.

    Full paths that repeat the same token (folder + file) can leave equal
    episode matches in the delegate list while already absent from name_dict.
    Stock RemoveMatch then raises ValueError inside list.remove.
    """

    def then(self, matches, when_response, context):  # pylint: disable=unused-argument
        if when_response is None:
            return
        if not isinstance(when_response, (list, tuple)):
            when_response = [when_response]
        for match in list(when_response):
            try:
                if match in matches:
                    matches.remove(match)
            except ValueError:
                continue


_MONTH_NAMES_PATTERN = '|'.join(
    sorted((re.escape(name) for name in MONTH_NAME_TO_NUMBER), key=len, reverse=True)
)

# Title ending with a month name: "Show Name Mai" / "Show Name August"
_TITLE_MONTH_RE = re.compile(
    r'^(?P<title>.+?)(?:[\s._-]+)(?P<month>' + _MONTH_NAMES_PATTERN + r')$',
    re.IGNORECASE,
)

# Month name + year anywhere in the release (spaces or dots), e.g.
# "Le Journal du Hard Mars 2012 JDH 03 2012" or "Show Name Mai 2016 ..."
# Require a non-letter/digit boundary so short tokens like "bre" do not match
# inside "cembre" (truncated Décembre display glitch). Use Unicode-aware
# letter/digit classes ([^\W_]) so Cyrillic/CJK month names are not glued to
# adjacent letters; '_' remains a valid separator.
# Trailing boundary is end or non-letter/digit so "(Avril-2021)" works.
_INPUT_MONTH_YEAR_RE = re.compile(
    r'(?<![^\W_])(?P<month>' + _MONTH_NAMES_PATTERN + r')[\s._-]+(?P<year>(?:19|20)\d{2})'
    r'(?:$|[\W_])',
    re.IGNORECASE,
)

# Scene tag: JDH 03 2012 / JDH-01-24 / JDH09-21 / JDH122022
_JDH_MONTH_YEAR_RE = re.compile(
    r'(?i)(?:^|[\s._\[(-])JDH[\s._-]*(?P<month>0?[1-9]|1[0-2])[\s._-]*'
    r'(?P<year>(?:19|20)\d{2}|\d{2})'
    r'(?:$|[^A-Za-z0-9])',
)

# Episode title that is only a month name (e.g. "3.aout" -> episode_title=aout)
_MONTH_ONLY_RE = re.compile(
    r'^(' + _MONTH_NAMES_PATTERN + r')$',
    re.IGNORECASE,
)

# Numeric monthly packs: MM.YYYY or YYYY.MM with 1 or 2 digit months.
# Optional spaces around separators cover "(2009 - 10)" style packs.
# Lookbehind blocks letters/digits/underscore so "Vol_1-2019" and "E02.2010" stay intact.
# Parenthesized years like "07.(2016)" do not match because '(' is not a date separator.
_NUMERIC_MONTH_YEAR_RE = re.compile(
    r'(?:^|(?<![0-9A-Za-z_]))'
    r'(?:'
    r'(?P<m1>0?[1-9]|1[0-2])\s*[._-]\s*(?P<y1>(?:19|20)\d{2})'
    r'|'
    r'(?P<y2>(?:19|20)\d{2})\s*[._-]\s*(?P<m2>0?[1-9]|1[0-2])'
    r')'
    r'(?:[^0-9]|$)'
)

# Dash-only MM-YY (2-digit year). Dots are excluded so weak pairs like
# "Show.Name.09.10" stay episodes, not month/year.
_NUMERIC_MONTH_SHORT_YEAR_RE = re.compile(
    r'(?:^|(?<![0-9A-Za-z_]))'
    r'(?P<month>0?[1-9]|1[0-2])-(?P<year>\d{2})'
    r'(?:$|[^0-9])'
)


def _is_valid_year(year):
    return 1920 <= year <= 2100


def _parse_year(year_value):
    """Parse a 2- or 4-digit year string/int into a full year.

    Two-digit years use pivot 50: 00-50 -> 2000-2050, 51-99 -> 1951-1999
    (covers Journal du Hard from the early 1990s and current packs).
    """
    if isinstance(year_value, int):
        year_str = str(year_value)
    else:
        year_str = str(year_value or '')
    if len(year_str) == 2 and year_str.isdigit():
        yy = int(year_str)
        return 2000 + yy if yy <= 50 else 1900 + yy
    if year_str.isdigit():
        return int(year_str)
    return None


def _single_int(value):
    if isinstance(value, list):
        if len(value) != 1:
            return None
        value = value[0]
    if isinstance(value, int):
        return value
    return None


def _unique_matches(match_list):
    """Deduplicate match objects for RemoveMatch.

    Rebulk Match equality is span/value/name/parent based, not identity.
    Passing two equal matches to RemoveMatch makes the second list.remove fail.
    """
    unique = []
    for match in match_list or []:
        if match is None:
            continue
        if match not in unique:
            unique.append(match)
    return unique


def _safe_removes(matches, match_list):
    """Deduplicate and keep only matches still present in the Matches object."""
    safe = []
    for match in _unique_matches(match_list):
        if match in matches:
            safe.append(match)
    return safe


def _path_segments(input_string):
    """Split a release name into path segments, closest to the file first.

    Library items are parsed as full paths, so the month/year token and a
    season folder can live in different segments.
    """
    segments = []
    start = 0
    for index, char in enumerate(input_string or ''):
        if char in '\\/':
            if index > start:
                segments.append((start, input_string[start:index]))
            start = index + 1
    if input_string and start < len(input_string):
        segments.append((start, input_string[start:]))
    return list(reversed(segments))


def _segment_has_sxxexx(sxxexx_matches, offset, segment):
    end = offset + len(segment)
    return any(match.start < end and match.end > offset for match in sxxexx_matches)


def _search_segments(regex, segments, sxxexx_matches, allow_sxxexx=False):
    """Search segments for a month/year pattern, skipping SxxExx segments.

    A season folder (Show S35/Show 01-2026.mkv) must not prevent the file name
    from being read as a monthly release, so SxxExx only blocks the segment it
    belongs to.
    """
    for offset, segment in segments:
        if not allow_sxxexx and _segment_has_sxxexx(sxxexx_matches, offset, segment):
            continue
        found = regex.search(segment)
        if found:
            return offset, segment, found
    return None, None, None


class CreateDateFromMonthYearRelease(Rule):
    """Create a date from MonthName.YYYY or MM.YYYY / YYYY.MM monthly releases.

    guessit -t episode "Show.Name.Mai.2016.HDTV.x264-GROUP"

    without this fix:
        {
            "title": "Show Name Mai",
            "year": 2016,
            "type": "episode"
        }

    with this fix:
        {
            "title": "Show Name",
            "date": "2016-05-01",
            "date_precision": "month",
            "type": "episode"
        }

    The date day is only a placeholder. Air-by-date matching uses year+month
    (date_precision=month), because monthly shows may air on another day
    (e.g. first Saturday of the month).

    Also converts weak year-as-season patterns (not SxxExx):
      Show.Name.10.2024 -> date 2024-10-01
      Show.Name.2011.01 -> date 2011-01-01
    """

    priority = POST_PROCESS
    consequence = [SafeRemoveMatch, AppendMatch]

    @staticmethod
    def _append_month_precision_date(to_append, start, end, year, month, input_string):
        """Append date + date_precision matches for a month-only release."""
        to_append.append(Match(
            start,
            end,
            name='date',
            value=first_date_of_month(year, month),
            input_string=input_string,
            tags=['month-year-date'],
        ))
        to_append.append(Match(
            start,
            end,
            name='date_precision',
            value='month',
            input_string=input_string,
            tags=['month-year-date'],
        ))

    def when(self, matches, context):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        """Evaluate the rule.

        :param matches:
        :type matches: rebulk.match.Matches
        :param context:
        :type context: dict
        :return:
        """
        if matches.named('date'):
            return

        to_remove = []
        to_append = []
        input_string = matches.input_string
        years = matches.named('year')
        titles = matches.named('title')
        seasons = matches.named('season')
        episodes = matches.named('episode')
        absolute_episodes = matches.named('absolute_episode') or []
        sxxexx_matches = [
            match
            for match in (seasons or []) + (episodes or [])
            if 'SxxExx' in (match.tags or [])
        ]
        segments = _path_segments(input_string)
        # Dash monthly packs like "(02-2021)" / "07-2025" are mis-parsed by
        # guessit as SxxExx with a season equal to the year (season=2021,
        # episode=2). A season whose value is a plausible year is the tell:
        # real seasons are small, so this never matches genuine SxxExx (S35E01).
        season_looks_like_year = any(
            _is_valid_year(value)
            for value in (_single_int(match.value) for match in (seasons or []))
            if value is not None
        )
        has_anime_absolute = any(
            'anime' in (match.tags or [])
            for match in absolute_episodes
        )

        # --- Pattern 0a: MonthName + YYYY in the raw release string -----------
        # Handles space-separated names and packs with trailing junk / JDH tags,
        # e.g. "Le Journal du Hard Mars 2012 JDH 03 2012 avi"
        # Truncated display glitches (Ao/cembre/vrier) are intentionally ignored.
        offset, segment, named = _search_segments(_INPUT_MONTH_YEAR_RE, segments, sxxexx_matches)
        if named:
            month = month_from_name(named.group('month'))
            year = int(named.group('year'))
            if month and _is_valid_year(year):
                to_remove.extend(years or [])
                to_remove.extend(seasons or [])
                to_remove.extend(episodes or [])
                to_remove.extend(absolute_episodes)
                if titles:
                    # Keep title text before the month token, taken from the
                    # matched segment so directory components of a full path
                    # do not leak into the title.
                    prefix = segment[:named.start('month')]
                    # Drop leading bracketed release tags: [CANAL+], [JDH], ...
                    prefix = re.sub(r'^\s*(?:[\[(][^\])]*[\])][\s._-]*)+', '', prefix)
                    # Drop a redundant numeric year/month right before the
                    # month name (…2022.07.Juillet.2022…)
                    prefix = re.sub(r'(?:19|20)\d{2}[\s._-]+\d{1,2}[\s._-]*$', '', prefix)
                    prefix = prefix.strip(' .-_([')
                    if prefix:
                        cleaned = re.sub(r'[\s._-]+', ' ', prefix).strip(' .-_([')
                        if cleaned:
                            new_title = copy.copy(titles[0])
                            new_title.value = cleaned
                            to_remove.extend(titles)
                            to_append.append(new_title)

                self._append_month_precision_date(
                    to_append,
                    offset + named.start('month'),
                    offset + named.end('year'),
                    year,
                    month,
                    input_string,
                )
                return _safe_removes(matches, to_remove), to_append

        # --- Pattern 0b: JDH MM YYYY / MM-YY / JDH122022 scene tags ------------
        offset, segment, jdh = _search_segments(_JDH_MONTH_YEAR_RE, segments, sxxexx_matches)
        if jdh:
            month = int(jdh.group('month'))
            year = _parse_year(jdh.group('year'))
            if year is not None and _is_valid_year(year):
                month_start = offset + jdh.start('month')
                to_remove.extend(years or [])
                to_remove.extend(seasons or [])
                to_remove.extend(episodes or [])
                to_remove.extend(absolute_episodes)
                if titles:
                    # Compact packs glue the tag to the month (JDH04-2022):
                    # the guessed title then swallows the month digits.
                    # Truncate it at the month start (JDH04 -> JDH).
                    title = titles[0]
                    if title.start < month_start <= title.end:
                        cleaned = input_string[title.start:month_start]
                        cleaned = re.sub(r'[\s._-]+', ' ', cleaned).strip(' .-_([')
                        if cleaned:
                            new_title = copy.copy(title)
                            new_title.value = cleaned
                            to_remove.extend(titles)
                            to_append.append(new_title)
                self._append_month_precision_date(
                    to_append,
                    month_start,
                    offset + jdh.end('year'),
                    year,
                    month,
                    input_string,
                )
                return _safe_removes(matches, to_remove), to_append

        # --- Pattern 1: title ends with month name + year match ---------------
        if years and titles:
            year_match = years[0]
            year = _single_int(year_match.value)
            if year is not None and _is_valid_year(year):
                for title in titles:
                    month_match = _TITLE_MONTH_RE.match(title.value)
                    if not month_match:
                        continue
                    month = month_from_name(month_match.group('month'))
                    if not month:
                        continue

                    new_title = copy.copy(title)
                    new_title.value = month_match.group('title').strip(' .-_')
                    to_remove.append(title)
                    to_append.append(new_title)

                    to_remove.extend(years)
                    to_remove.extend(matches.named('season'))
                    to_remove.extend(matches.named('episode'))

                    self._append_month_precision_date(
                        to_append,
                        year_match.start,
                        year_match.end,
                        year,
                        month,
                        year_match.input_string,
                    )
                    return _safe_removes(matches, to_remove), to_append

        # --- Pattern 2: adjacent MM.YYYY or YYYY.MM (1 or 2 digit month) ------
        # Skip real SxxExx and anime absolute-episode packs (e.g. Show.-.5.2016),
        # but still handle dash monthly packs mis-parsed as season==year.
        if not has_anime_absolute or season_looks_like_year:
            offset, segment, numeric = _search_segments(
                _NUMERIC_MONTH_YEAR_RE, segments, sxxexx_matches,
                allow_sxxexx=season_looks_like_year,
            )
            if numeric:
                if numeric.group('y1'):
                    year = int(numeric.group('y1'))
                    month = int(numeric.group('m1'))
                else:
                    year = int(numeric.group('y2'))
                    month = int(numeric.group('m2'))

                if _is_valid_year(year):
                    to_remove.extend(seasons or [])
                    to_remove.extend(episodes or [])
                    to_remove.extend(years or [])
                    to_remove.extend(matches.named('absolute_episode'))

                    if numeric.group('y1'):
                        span_start = numeric.start('m1')
                        span_end = numeric.end('y1')
                    else:
                        span_start = numeric.start('y2')
                        span_end = numeric.end('m2')

                    self._append_month_precision_date(
                        to_append,
                        offset + span_start,
                        offset + span_end,
                        year,
                        month,
                        input_string,
                    )
                    return _safe_removes(matches, to_remove), to_append

        # --- Pattern 2b: dash-only MM-YY (2-digit year) -----------------------
        # guessit often turns "09-24" into an episode range; allow past anime
        # absolute tags. Real SxxExx still blocked. Dot pairs (09.10) excluded
        # by the regex.
        # Years 01-12 are ambiguous with episode ranges (02-03, 1-12) — skip
        # those here; JDH-prefixed packs still use pattern 0b.
        offset, segment, short = _search_segments(
            _NUMERIC_MONTH_SHORT_YEAR_RE, segments, sxxexx_matches,
            allow_sxxexx=season_looks_like_year,
        )
        if short:
            month = int(short.group('month'))
            year_token = short.group('year')
            year = _parse_year(year_token)
            if (
                year is not None
                and _is_valid_year(year)
                and int(year_token) > 12
            ):
                to_remove.extend(seasons or [])
                to_remove.extend(episodes or [])
                to_remove.extend(years or [])
                to_remove.extend(absolute_episodes)
                self._append_month_precision_date(
                    to_append,
                    offset + short.start('month'),
                    offset + short.end('year'),
                    year,
                    month,
                    input_string,
                )
                return _safe_removes(matches, to_remove), to_append

        # --- Pattern 3: day + month name in episode_title, year elsewhere ------
        episode_titles = matches.named('episode_title')
        if years and episodes and episode_titles:
            year = _single_int(years[0].value)
            day = _single_int(episodes[0].value)
            month_title = episode_titles[0]
            month = None
            if _MONTH_ONLY_RE.match(str(month_title.value or '')):
                month = month_from_name(month_title.value)

            if (
                year is not None
                and _is_valid_year(year)
                and day is not None
                and 1 <= day <= 31
                and month is not None
            ):
                try:
                    parsed = date(year, month, day)
                except ValueError:
                    parsed = None
                if parsed:
                    to_remove.extend(years)
                    to_remove.extend(episodes)
                    to_remove.extend(episode_titles)
                    to_remove.extend(seasons)
                    to_append.append(Match(
                        years[0].start,
                        years[0].end,
                        name='date',
                        value=parsed,
                        input_string=years[0].input_string,
                        tags=['month-year-date'],
                    ))
                    return _safe_removes(matches, to_remove), to_append

        return
