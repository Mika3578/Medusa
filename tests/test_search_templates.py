# coding=utf-8
"""Tests for medusa.search_templates module."""
from __future__ import unicode_literals

import pytest
from medusa import db
from medusa.search_templates import SearchTemplates


@pytest.fixture
def setup_search_templates(create_tvshow):
    """Set up a test show with search templates."""
    show = create_tvshow(indexerid=1, indexer=1, name='Test Show', anime=False)

    # Initialize search templates
    show.init_search_templates()

    return show


@pytest.fixture
def db_connection():
    """Get a database connection."""
    return db.DBConnection()


class TestSearchTemplates(object):
    """Test SearchTemplates class."""

    def test_custom_template_persists_after_update(self, setup_search_templates, db_connection):
        """Test that custom templates persist after update() is called."""
        show = setup_search_templates

        # Create a custom template
        custom_template = {
            'template': 'CustomTemplate S%0SE%0E',
            'title': 'Custom Title',
            'season': -1,
            'enabled': True,
            'default': False,
            'seasonSearch': False
        }

        # Save the custom template
        show.search_templates.save(custom_template)

        # Verify it was saved
        templates_before = db_connection.select(
            'SELECT * FROM search_templates '
            'WHERE indexer=? AND series_id=? AND `default`=0',
            [show.indexer, show.series_id]
        )
        assert len(templates_before) == 1
        assert templates_before[0]['template'] == 'CustomTemplate S%0SE%0E'

        # Call update with a list of templates including the custom one
        show.search_templates.update([custom_template])

        # Verify the custom template still exists
        templates_after = db_connection.select(
            'SELECT * FROM search_templates '
            'WHERE indexer=? AND series_id=? AND `default`=0',
            [show.indexer, show.series_id]
        )
        assert len(templates_after) == 1
        assert templates_after[0]['template'] == 'CustomTemplate S%0SE%0E'

    def test_custom_template_survives_clean(self, setup_search_templates, db_connection):
        """Test that custom templates survive _clean() even without scene exceptions."""
        show = setup_search_templates

        # Create a custom template with a title that doesn't have a scene exception
        custom_template = {
            'template': 'NoSceneException S%0SE%0E',
            'title': 'NonExistentSceneException',
            'season': -1,
            'enabled': True,
            'default': False,
            'seasonSearch': False
        }

        # Save the custom template
        show.search_templates.save(custom_template)

        # Verify it was saved
        templates_before = db_connection.select(
            'SELECT * FROM search_templates '
            'WHERE indexer=? AND series_id=? AND title=? AND `default`=0',
            [show.indexer, show.series_id, 'NonExistentSceneException']
        )
        assert len(templates_before) == 1

        # Call _clean() which should not delete custom templates
        show.search_templates._clean()

        # Verify the custom template still exists
        templates_after = db_connection.select(
            'SELECT * FROM search_templates '
            'WHERE indexer=? AND series_id=? AND title=? AND `default`=0',
            [show.indexer, show.series_id, 'NonExistentSceneException']
        )
        assert len(templates_after) == 1

    def test_default_templates_without_exceptions_removed(self, setup_search_templates, db_connection):
        """Test that default templates without scene exceptions are removed by _clean()."""
        show = setup_search_templates

        # Manually insert a default template with a title that doesn't have a scene exception
        db_connection.action(
            'INSERT INTO search_templates (template, title, indexer, series_id, season, enabled, `default`, season_search) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            ['OrphanedDefault S%0SE%0E', 'OrphanedTitle', show.indexer, show.series_id, -1, 1, 1, 0]
        )

        # Verify it was inserted
        templates_before = db_connection.select(
            'SELECT * FROM search_templates '
            'WHERE indexer=? AND series_id=? AND title=? AND `default`=1',
            [show.indexer, show.series_id, 'OrphanedTitle']
        )
        assert len(templates_before) == 1

        # Call _clean() which should delete this orphaned default template
        show.search_templates._clean()

        # Verify the default template was deleted
        templates_after = db_connection.select(
            'SELECT * FROM search_templates '
            'WHERE indexer=? AND series_id=? AND title=? AND `default`=1',
            [show.indexer, show.series_id, 'OrphanedTitle']
        )
        assert len(templates_after) == 0

    def test_custom_templates_without_exceptions_preserved(self, setup_search_templates, db_connection):
        """Test that custom templates without scene exceptions are preserved by _clean()."""
        show = setup_search_templates

        # Create a custom template with a title that doesn't have a scene exception
        custom_template = {
            'template': 'CustomNoException S%0SE%0E',
            'title': 'CustomWithoutException',
            'season': -1,
            'enabled': True,
            'default': False,
            'seasonSearch': False
        }

        # Save the custom template
        show.search_templates.save(custom_template)

        # Verify it was saved
        templates_before = db_connection.select(
            'SELECT * FROM search_templates '
            'WHERE indexer=? AND series_id=? AND title=? AND `default`=0',
            [show.indexer, show.series_id, 'CustomWithoutException']
        )
        assert len(templates_before) == 1

        # Call _clean() which should NOT delete custom templates
        show.search_templates._clean()

        # Verify the custom template still exists
        templates_after = db_connection.select(
            'SELECT * FROM search_templates '
            'WHERE indexer=? AND series_id=? AND title=? AND `default`=0',
            [show.indexer, show.series_id, 'CustomWithoutException']
        )
        assert len(templates_after) == 1

    def test_templates_exist_after_read_from_db(self, setup_search_templates):
        """Test that templates exist after read_from_db() is called."""
        show = setup_search_templates

        # Create a custom template
        custom_template = {
            'template': 'TestTemplate S%0SE%0E',
            'title': 'Test Title',
            'season': -1,
            'enabled': True,
            'default': False,
            'seasonSearch': False
        }

        # Save the custom template
        show.search_templates.save(custom_template)

        # Call read_from_db()
        show.search_templates.read_from_db()

        # Verify templates are populated
        assert show.search_templates.templates is not None
        assert len(show.search_templates.templates) > 0

        # Verify the custom template is in the list
        custom_templates = [t for t in show.search_templates.templates if not t.default]
        assert len(custom_templates) > 0
        assert any(t.template == 'TestTemplate S%0SE%0E' for t in custom_templates)

    def test_missing_default_value_handled_defensively(self, setup_search_templates, db_connection):
        """Test that missing 'default' values are handled with defensive get() method."""
        show = setup_search_templates

        # Create a template without the 'default' key
        template_without_default = {
            'template': 'NoDefault S%0SE%0E',
            'title': 'Test Show',  # Use the actual show name
            'season': -1,
            'enabled': True,
            'seasonSearch': False
        }

        # This should not raise an exception
        show.search_templates.save(template_without_default)

        # Verify it was saved with default=False (the defensive default)
        templates = db_connection.select(
            'SELECT * FROM search_templates '
            'WHERE indexer=? AND series_id=? AND template=?',
            [show.indexer, show.series_id, 'NoDefault S%0SE%0E']
        )
        assert len(templates) == 1
        # Should be saved as default=0 (False) since template.get('default', False) was used
        assert templates[0]['default'] == 0

    def test_update_with_missing_default_value(self, setup_search_templates):
        """Test that update() handles templates with missing 'default' value."""
        show = setup_search_templates

        # Create a template without the 'default' key
        template_without_default = {
            'template': 'UpdateNoDefault S%0SE%0E',
            'title': 'Test Show',  # Use the actual show name
            'season': -1,
            'enabled': True,
            'seasonSearch': False
        }

        # This should not raise an exception
        result = show.search_templates.update([template_without_default])

        # Verify the template was added
        assert result is not None
        assert len(result) > 0

    def test_custom_template_skips_scene_exception_validation(self, setup_search_templates):
        """Test that custom templates skip scene exception validation in update()."""
        show = setup_search_templates

        # Create a custom template with a title that doesn't have a scene exception
        custom_template = {
            'template': 'CustomSkipValidation S%0SE%0E',
            'title': 'NoSceneExceptionForThis',
            'season': -1,
            'enabled': True,
            'default': False,  # Custom template
            'seasonSearch': False
        }

        # This should NOT skip the template due to missing scene exception
        result = show.search_templates.update([custom_template])

        # Verify the custom template was added despite no scene exception
        assert result is not None
        custom_templates = [t for t in result if not t.default and t.title == 'NoSceneExceptionForThis']
        assert len(custom_templates) == 1
        assert custom_templates[0].template == 'CustomSkipValidation S%0SE%0E'

    def test_default_template_requires_scene_exception_or_show_name(self, setup_search_templates):
        """Test that default templates require scene exception or show name in update()."""
        show = setup_search_templates

        # Create a default template with a title that doesn't have a scene exception
        # and is not the show name
        default_template = {
            'template': 'DefaultNeedsValidation S%0SE%0E',
            'title': 'NoSceneExceptionForThis',
            'season': -1,
            'enabled': True,
            'default': True,  # Default template
            'seasonSearch': False
        }

        # This SHOULD skip the template due to missing scene exception
        result = show.search_templates.update([default_template])

        # Verify the default template was NOT added due to missing scene exception
        assert result is not None
        default_templates = [t for t in result if t.default and t.title == 'NoSceneExceptionForThis']
        assert len(default_templates) == 0

    def test_search_templates_property_initializes_if_none(self, create_tvshow):
        """Test that search_templates property initializes _search_templates if None."""
        show = create_tvshow(indexerid=2, indexer=1, name='Test Show 2', anime=False)

        # Don't call init_search_templates() manually
        # The property should handle initialization

        # Access search_templates property
        templates = show.search_templates

        # Verify that templates were initialized
        assert templates is not None
        assert show._search_templates is not None
        assert hasattr(templates, 'templates')

    def test_provider_can_access_search_templates(self, setup_search_templates):
        """Test that provider code can access search_templates.templates."""
        show = setup_search_templates

        # Create a custom template
        custom_template = {
            'template': 'ProviderTest S%0SE%0E',
            'title': 'Test Show',
            'season': -1,
            'enabled': True,
            'default': False,
            'seasonSearch': False
        }

        # Save the custom template
        show.search_templates.save(custom_template)

        # Simulate provider code accessing templates
        # This is how generic_provider.py accesses templates
        templates_list = show.search_templates.templates

        # Verify templates are accessible
        assert templates_list is not None
        assert isinstance(templates_list, list)
        assert len(templates_list) > 0

        # Verify we can iterate and access template properties
        for template in templates_list:
            assert hasattr(template, 'template')
            assert hasattr(template, 'title')
            assert hasattr(template, 'season')
            assert hasattr(template, 'enabled')
            assert hasattr(template, 'default')
            assert hasattr(template, 'season_search')

