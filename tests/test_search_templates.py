# coding=utf-8
"""Tests for medusa.search_templates module."""
from __future__ import unicode_literals

from mock import MagicMock, patch, call

from medusa.search_templates import SearchTemplate, SearchTemplates

import pytest


def _make_show(indexer=1, series_id=100, name='My Show'):
    """Create a minimal mock show object."""
    show = MagicMock()
    show.indexer = indexer
    show.series_id = series_id
    show.name = name
    show.air_by_date = False
    show.sports = False
    show.anime = False
    show.is_scene = False
    show.aliases = []
    return show


def _make_db(select_return=None, action_return=None):
    """Create a mock DBConnection."""
    db = MagicMock()
    db.select.return_value = select_return or []
    db.action.return_value = action_return
    db.upsert.return_value = None
    return db


# ---------------------------------------------------------------------------
# Helpers to build template dicts (as they arrive from the API / UI)
# ---------------------------------------------------------------------------

def _default_template_dict(title='My Show', season=-1):
    return {
        'title': title,
        'template': '%SN S%0SE%0E',
        'season': season,
        'enabled': True,
        'default': 1,
        'seasonSearch': 0,
    }


def _custom_template_dict(title='My Show', season=-1):
    return {
        'title': title,
        'template': '%SN+custom+%0E',
        'season': season,
        'enabled': True,
        'default': 0,
        'seasonSearch': 0,
    }


# ---------------------------------------------------------------------------
# 1. Custom template persists after update()
# ---------------------------------------------------------------------------

class TestUpdateCustomTemplates:
    def test_custom_template_is_saved(self):
        """Custom templates (default=0) must be saved regardless of scene exceptions."""
        show = _make_show()
        db = _make_db(select_return=[])  # no scene exceptions found

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        templates = [_custom_template_dict()]
        result = sut.update(templates)

        # The custom template must be in the returned list
        assert len(result) == 1
        assert result[0].template == '%SN+custom+%0E'
        assert not result[0].default

        # upsert must have been called to persist it
        db.upsert.assert_called_once()

    def test_custom_template_with_unknown_title_is_saved(self):
        """Custom templates whose title is not in scene_exceptions must still be saved."""
        show = _make_show()
        db = _make_db(select_return=[])  # scene exception query returns nothing

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        # Title that does not match the show name and is not in scene_exceptions
        templates = [_custom_template_dict(title='Unknown Alias')]
        result = sut.update(templates)

        assert len(result) == 1
        assert result[0].title == 'Unknown Alias'

    def test_default_template_without_scene_exception_is_skipped(self):
        """Default templates (default=1) whose scene exception no longer exists are skipped."""
        show = _make_show()
        db = _make_db(select_return=[])  # no scene exceptions found

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        templates = [_default_template_dict(title='Removed Alias')]
        result = sut.update(templates)

        # Should be skipped because scene exception doesn't exist
        assert result == []
        db.upsert.assert_not_called()

    def test_default_template_for_show_name_is_always_saved(self):
        """Default templates using the actual show name are always saved."""
        show = _make_show(name='My Show')
        db = _make_db(select_return=[])  # scene exception query returns nothing

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        templates = [_default_template_dict(title='My Show')]
        result = sut.update(templates)

        assert len(result) == 1
        assert result[0].title == 'My Show'

    def test_missing_default_key_treated_as_custom(self):
        """Templates missing the 'default' key are treated as custom (saved unconditionally)."""
        show = _make_show()
        db = _make_db(select_return=[])

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        template = _custom_template_dict(title='Unknown Alias')
        del template['default']  # simulate missing key

        result = sut.update([template])

        # Should be saved as a custom template (default missing == falsy)
        assert len(result) == 1

    def test_mixed_custom_and_default_templates(self):
        """Only custom templates and default templates with valid scene exceptions are saved."""
        show = _make_show(name='My Show')

        def fake_select(query, params=None):
            # scene_exceptions query for the stale default alias returns nothing
            if params and 'Stale Alias' in params:
                return []
            return []

        db = MagicMock()
        db.select.side_effect = fake_select
        db.upsert.return_value = None
        db.action.return_value = None

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        templates = [
            _custom_template_dict(title='Custom Title'),      # custom - always saved
            _default_template_dict(title='Stale Alias'),      # default, no exception -> skipped
            _default_template_dict(title='My Show'),          # default, matches show name -> saved
        ]
        result = sut.update(templates)

        titles = [t.title for t in result]
        assert 'Custom Title' in titles
        assert 'My Show' in titles
        assert 'Stale Alias' not in titles


# ---------------------------------------------------------------------------
# 2. Custom template survives _clean()
# ---------------------------------------------------------------------------

class TestClean:
    def test_clean_only_deletes_default_templates(self):
        """_clean() must include AND `default` = 1 so custom templates are never removed."""
        show = _make_show()
        db = _make_db()

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        sut._clean()

        # Verify the DELETE query was called with `default` = 1 constraint
        db.action.assert_called_once()
        call_args = db.action.call_args
        sql = call_args[0][0]

        assert '`default` = 1' in sql, (
            '_clean() must restrict deletion to default templates (default = 1)'
        )

    def test_clean_does_not_contain_unguarded_delete(self):
        """_clean() must NOT delete rows without the default=1 guard."""
        show = _make_show()
        db = _make_db()

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        sut._clean()

        sql = db.action.call_args[0][0]
        # There must be exactly one DELETE and it must have the default=1 guard
        assert 'DELETE' in sql.upper()
        assert '`default` = 1' in sql


# ---------------------------------------------------------------------------
# 3. Default templates without scene exceptions are removed by _clean()
# ---------------------------------------------------------------------------

class TestCleanDefaultTemplates:
    def test_clean_passes_correct_parameters(self):
        """_clean() must pass indexer/series_id/show_name as parameters."""
        show = _make_show(indexer=2, series_id=42, name='Test Show')
        db = _make_db()

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        sut._clean()

        params = db.action.call_args[0][1]
        assert 2 in params        # indexer appears
        assert 42 in params       # series_id appears
        assert 'Test Show' in params  # show name guard


# ---------------------------------------------------------------------------
# 4. Templates remain available after read_from_db()
# ---------------------------------------------------------------------------

class TestReadFromDb:
    def _make_db_row(self, search_template_id=1, template='%SN S%0SE%0E',
                     title='My Show', season=-1, enabled=1, default=0, season_search=0):
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            'search_template_id': search_template_id,
            'template': template,
            'title': title,
            'season': season,
            'enabled': enabled,
            'default': default,
            'season_search': season_search,
        }[key]
        return row

    def test_custom_template_is_present_after_read_from_db(self):
        """Custom templates read from db must appear in self.templates."""
        show = _make_show()
        db_row = self._make_db_row(template='%SN+custom', title='My Show', default=0)

        db = MagicMock()
        db.action.return_value = None
        db.select.return_value = [db_row]

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        sut.read_from_db()

        assert len(sut.templates) == 1
        assert sut.templates[0].template == '%SN+custom'
        assert not sut.templates[0].default

    def test_default_template_is_present_after_read_from_db(self):
        """Default templates read from db must appear in self.templates."""
        show = _make_show()
        db_row = self._make_db_row(template='%SN S%0SE%0E', title='My Show', default=1)

        db = MagicMock()
        db.action.return_value = None
        db.select.return_value = [db_row]

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        sut.read_from_db()

        assert len(sut.templates) == 1
        assert sut.templates[0].default is True

    def test_multiple_templates_loaded_correctly(self):
        """Multiple templates (custom + default) are all loaded from db."""
        show = _make_show()
        rows = [
            self._make_db_row(search_template_id=1, template='%SN S%0SE%0E', default=1),
            self._make_db_row(search_template_id=2, template='%SN+custom', default=0),
        ]

        db = MagicMock()
        db.action.return_value = None
        db.select.return_value = rows

        sut = SearchTemplates(show_obj=show)
        sut.main_db_con = db

        sut.read_from_db()

        assert len(sut.templates) == 2
