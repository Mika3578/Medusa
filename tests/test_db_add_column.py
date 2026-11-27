# coding=utf-8
"""SQLite coverage for the addColumn database helper."""

import sqlite3
import threading

from medusa import db

from mock.mock import Mock

import pytest


@pytest.fixture
def database(monkeypatch):
    """Run addColumn against a private in-memory database."""
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE shows (id INTEGER PRIMARY KEY, name TEXT)')
    connection.execute("INSERT INTO shows VALUES (1, 'Show Name')")
    connection.commit()

    database = object.__new__(db.DBConnection)
    database.filename = 'add-column-{0}'.format(id(connection))
    database.row_type = 'dict'
    database.connection = connection
    monkeypatch.setitem(db.db_locks, database.filename, threading.Lock())
    monkeypatch.setattr(db.logger, 'log', Mock())

    yield database
    connection.close()


def column_names(database, table):
    """Read the column names of a table."""
    return [row['name'] for row in database.select('PRAGMA table_info(`{table}`)'.format(table=table))]


def error_log_calls():
    """Collect the error-level log calls made while the test ran."""
    return [call for call in db.logger.log.call_args_list
            if len(call.args) >= 2 and call.args[1] == db.logger.ERROR]


def test_add_column_creates_missing_column_with_default(database):
    """A missing column is created and its existing rows get the default value."""
    database.addColumn('shows', 'quality', 'NUMERIC', 5)

    assert 'quality' in column_names(database, 'shows')
    assert database.select('SELECT quality FROM shows') == [{'quality': 5}]


def test_add_column_skips_existing_column(database):
    """An existing column keeps its data and the attempt is only logged at debug level."""
    database.addColumn('shows', 'quality', 'NUMERIC', 5)
    database.action('UPDATE shows SET quality = 42')

    database.addColumn('shows', 'quality', 'NUMERIC', 5)

    assert database.select('SELECT quality FROM shows') == [{'quality': 42}]
    assert error_log_calls() == []
    assert any('already exists' in str(call.args[0]) for call in db.logger.log.call_args_list
               if len(call.args) >= 2 and call.args[1] == db.logger.DEBUG)


def test_add_column_tolerates_column_created_by_concurrent_request(database, monkeypatch):
    """A column created between the existence check and the alteration is tolerated."""
    database.addColumn('shows', 'size', 'NUMERIC', 0)
    database.action('UPDATE shows SET size = 42')
    monkeypatch.setattr(database, 'hasColumn', Mock(return_value=False))

    database.addColumn('shows', 'size', 'NUMERIC', 0)

    assert database.select('SELECT size FROM shows') == [{'size': 42}]
    assert error_log_calls() == []


def test_add_column_reraises_unexpected_database_error(database):
    """Database errors other than an existing column are still raised."""
    with pytest.raises(sqlite3.OperationalError, match='no such table'):
        database.addColumn('missing_table', 'size', 'NUMERIC', 0)


def test_schema_upgrade_add_column_delegates_to_connection(database):
    """Schema upgrades add missing columns through the connection."""
    schema = db.SchemaUpgrade(database)

    schema.addColumn('shows', 'quality', 'NUMERIC', 5)

    assert database.select('SELECT quality FROM shows') == [{'quality': 5}]


def test_schema_upgrade_add_column_skips_existing_column(database):
    """Schema upgrades tolerate a column that already exists."""
    schema = db.SchemaUpgrade(database)
    schema.addColumn('shows', 'quality', 'NUMERIC', 5)
    database.action('UPDATE shows SET quality = 42')

    schema.addColumn('shows', 'quality', 'NUMERIC', 0)

    assert database.select('SELECT quality FROM shows') == [{'quality': 42}]
