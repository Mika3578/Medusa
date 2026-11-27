# coding=utf-8
"""Regression tests for probe requests on the web root dispatcher."""

from unittest.mock import Mock

from medusa.server.web.core.base import WebHandler, WebRoot

import pytest

from tornado.web import Application

HOME_BODY = '<main>Medusa home</main>'


@pytest.fixture
def reported_errors(monkeypatch, app_config):
    """Silence authentication and detect exceptions reported as errors."""
    app_config('WEB_USERNAME', '')
    app_config('WEB_PASSWORD', '')
    app_config('WEB_ROOT', '')
    app_config('DEFAULT_PAGE', 'home')
    exceptions = Mock()
    monkeypatch.setattr('medusa.server.web.core.base.exception_handler.handle', exceptions)
    return exceptions


@pytest.fixture
def home_shell(monkeypatch, reported_errors):
    """Render a known shell for routes converted to VueRouter."""
    template = Mock()
    template.render.return_value = HOME_BODY
    monkeypatch.setattr('medusa.server.web.home.handler.PageTemplate', Mock(return_value=template))
    return reported_errors


@pytest.fixture
def app(home_shell):
    """Exercise the actual WebRoot dispatcher through a local Tornado application."""
    from medusa.server.web.home.handler import Home

    return Application([(r'/home(/?.*)', Home), (r'(/?.*)', WebRoot)])


@pytest.mark.gen_test
@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('query', ['', 'rest_route=/wp-json/wp/v2/users', 'phpinfo=1'])
async def test_web_root_redirects_probes_without_reporting_errors(http_client, base_url, home_shell, method, query):
    """Probing the web root with unexpected query arguments redirects, instead of reporting an error."""
    options = {'method': method}
    if method == 'POST':
        options['body'] = ''

    response = await http_client.fetch(base_url + '/?' + query, follow_redirects=False, raise_error=False, **options)

    assert response.code == 302
    assert response.headers['Location'] == '/home/'
    home_shell.assert_not_called()


@pytest.mark.gen_test
async def test_home_route_ignores_unexpected_arguments(http_client, base_url, home_shell):
    """Unexpected query arguments don't break a route function that takes no arguments."""
    response = await http_client.fetch(base_url + '/home/status/?rest_route=/wp-json/wp/v2/users')

    assert response.code == 200
    assert response.body == HOME_BODY.encode('utf-8')
    home_shell.assert_not_called()


def test_filter_route_arguments_passes_everything_to_kwargs_route():
    """Route functions accepting arbitrary arguments receive all request arguments."""
    def route(**query_args):
        pass

    kwargs = {'known': 'value', 'unexpected': 'value'}

    assert WebHandler.filter_route_arguments(route, kwargs) == kwargs


def test_filter_route_arguments_drops_unexpected_arguments(monkeypatch):
    """Route functions with named arguments only receive the arguments they accept, logged at debug level."""
    log = Mock()
    monkeypatch.setattr('medusa.server.web.core.base.logger.log', log)

    def route(known=None):
        pass

    kwargs = {'known': 'value', 'unexpected': 'value'}

    assert WebHandler.filter_route_arguments(route, kwargs) == {'known': 'value'}
    assert any('unexpected' in str(call.args[0]) for call in log.call_args_list)


def test_filter_route_arguments_for_bound_and_static_routes():
    """Bound and static route functions are filtered by their declared signature."""
    class Route(object):
        def index(self):
            return 'index'

        @staticmethod
        def notify(message=None):
            return message

    assert WebHandler.filter_route_arguments(Route().index, {'rest_route': '/wp-json/wp/v2/users'}) == {}
    assert WebHandler.filter_route_arguments(Route.notify, {'message': 'sent'}) == {'message': 'sent'}


def test_filter_route_arguments_keeps_arguments_for_uncallable_route():
    """Arguments are kept for a route dispatched to a non-callable attribute, preserving the previous behavior."""
    assert WebHandler.filter_route_arguments('not-callable', {'unexpected': 'value'}) == {'unexpected': 'value'}
