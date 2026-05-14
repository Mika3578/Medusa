#!/usr/bin/env python
# coding=utf-8
"""Dredd hook."""
from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import io
import json
import os
import sys

try:
    from builtins import print as real_print
except ImportError:
    # Python 2
    from __builtin__ import print as real_print

current_dir = os.path.abspath(os.path.dirname(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.insert(1, os.path.join(root_dir, 'ext'))
sys.path.insert(1, os.path.join(root_dir, 'ext%d' % sys.version_info.major))

from configparser import ConfigParser

import dredd_hooks as hooks

from six import string_types
from six.moves.collections_abc import Mapping
from six.moves.urllib.error import HTTPError
from six.moves.urllib.parse import parse_qs, urlencode, urlparse
from six.moves.urllib.request import Request, urlopen

import yaml


api_description = None

stash = {
    'web-username': 'testuser',
    'web-password': 'testpass',
    'api-key': '1234567890ABCDEF1234567890ABCDEF',
}

alias_fixture = {
    'series': 'tvdb301824',
    'name': 'TheBig',
    'type': 'local',
}

hook_log = os.path.join(current_dir, 'hook.log')
try:
    os.remove(hook_log)
except OSError:
    pass


def print(*args, **kwargs):
    """Override builtin print to write to a file, because nothing prints to `stdout`."""
    with io.open(hook_log, 'a', encoding='utf-8') as fh:
        kwargs['file'] = fh
        return real_print(*args, **kwargs)


def api_request(method, path, body=None):
    """Perform an API request against the Dredd test server."""
    headers = {
        'Accept': 'application/json; charset=UTF-8',
        'Content-Type': 'application/json',
        'x-api-key': stash['api-key'],
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')

    request = Request('http://localhost:8081' + path, data=data, headers=headers)
    request.get_method = lambda: method

    try:
        response = urlopen(request)
        return response.getcode(), response.read().decode('utf-8')
    except HTTPError as error:
        return error.code, error.read().decode('utf-8')


def contains_expression(value, expression):
    """Return whether the provided expression is present in the value."""
    if isinstance(value, string_types):
        return value == expression
    elif isinstance(value, Mapping):
        return any(contains_expression(item, expression) for item in value.values())
    elif isinstance(value, list):
        return any(contains_expression(item, expression) for item in value)

    return False


def ensure_alias():
    """Ensure the stashed alias exists for alias-dependent transactions."""
    alias_id = stash.get('alias-id')
    if alias_id:
        status_code, _ = api_request('GET', '/api/v2/alias/{0}'.format(alias_id))
        if status_code == 200:
            return alias_id

    status_code, response_body = api_request('POST', '/api/v2/alias', alias_fixture)
    if status_code != 201:
        raise RuntimeError('Unable to create alias fixture (status {0}): {1}'.format(status_code, response_body))

    body = json.loads(response_body)
    stash['alias-id'] = body['id']
    print('Prepared alias fixture {alias_id!r}'.format(alias_id=body['id']))
    return body['id']


@hooks.before_all
def order_and_load_api_description(transactions):
    """Load api description."""
    global api_description

    # Set DELETE transactions last, keep the rest unchanged
    transactions.sort(key=lambda x: (x['request']['method'] == 'DELETE', True))

    with io.open(transactions[0]['origin']['filename'], 'rb') as stream:
        api_description = yaml.safe_load(stream)


@hooks.before_each
def configure_transaction(transaction):
    """Configure request based on x- property values for each response code."""
    base_path = api_description['basePath']

    path = transaction['origin']['resourceName']
    method = transaction['request']['method']
    status_code = int(transaction['expected']['statusCode'])
    response = api_description['paths'][path[len(base_path):]][method.lower()]['responses'][status_code]

    # Whether we should skip this test
    transaction['skip'] = response.get('x-disabled', False)

    # Add api-key
    if not response.get('x-no-api-key', False):
        transaction['request']['headers']['x-api-key'] = stash['api-key']

    # If no body is expected, skip body validation
    expected = transaction['expected']
    expected_content_type = expected['headers'].get('Content-Type')
    expected_status_code = int(expected['statusCode'])
    if expected_status_code == 204 or response.get('x-expect', {}).get('no-body', False):
        if expected.get('body'):
            del expected['body']
        if expected_content_type:
            print('Skipping content-type validation for {name!r}.'.format(name=transaction['name']))
            del expected['headers']['Content-Type']

    # Keep stash configuration in the transaction to be executed in an after hook
    transaction['x-stash'] = response.get('x-stash') or {}

    request = response.get('x-request', {})
    if contains_expression(request, "${stash['alias-id']}"):
        ensure_alias()

    # Change request based on x-request configuration
    url = transaction['fullPath']
    parsed_url = urlparse(url)
    parsed_params = parse_qs(parsed_url.query)
    parsed_path = parsed_url.path

    body = request.get('body')
    body_update = request.get('body-update')
    if body is not None:
        transaction['request']['body'] = json.dumps(evaluate(body))
    elif body_update is not None:
        try:
            orig_body = json.loads(transaction['request']['body'])
        except ValueError:
            orig_body = {}

        # Use the current request body and update it with the new values
        new_body = dict(orig_body, **evaluate(body_update))
        transaction['request']['body'] = json.dumps(new_body)

    path_params = request.get('path-params')
    if path_params:
        params = {}
        resource_parts = path.split('/')
        for i, part in enumerate(url.split('/')):
            if not part:
                continue

            resource_part = resource_parts[i]
            if resource_part[0] == '{' and resource_part[-1] == '}':
                params[resource_part[1:-1]] = part

        params.update(path_params)
        new_url = path
        for name, value in params.items():
            value = evaluate(value)
            new_url = new_url.replace('{' + name + '}', str(value))

        replace_url(transaction, new_url)

    query_params = request.get('query-params')
    if query_params:
        for name, value in query_params.items():
            query_params[name] = evaluate(value)

        query_params = dict(parsed_params, **query_params)
        new_url = parsed_path if not query_params else parsed_path + '?' + urlencode(query_params)

        replace_url(transaction, new_url)


@hooks.after_each
def stash_values(transaction):
    """Stash values."""
    if 'real' in transaction and 'bodySchema' in transaction['expected']:
        body = json.loads(transaction['real']['body']) if transaction['real']['body'] else None
        headers = transaction['real']['headers']
        for name, value in transaction['x-stash'].items():
            value = evaluate(value, {'body': body, 'headers': headers})
            print('Stashing {name}: {value!r}'.format(name=name, value=value))
            stash[name] = value


def replace_url(transaction, new_url):
    """Replace with a new URL."""
    transaction['fullPath'] = new_url
    transaction['request']['uri'] = new_url
    transaction['id'] = transaction['request']['method'] + ' ' + new_url


def evaluate(expression, context=None):
    """Evaluate the expression value."""
    context = context or {'stash': stash}
    if isinstance(expression, string_types) and expression.startswith('${') and expression.endswith('}'):
        value = eval(expression[2:-1], context)
        print('Expression {expression} evaluated to {value!r}'.format(expression=expression, value=value))
        return value
    elif isinstance(expression, Mapping):
        for key, value in expression.items():
            expression[key] = evaluate(value, context=context)
    elif isinstance(expression, list):
        for i, value in enumerate(expression):
            expression[i] = evaluate(value, context=context)

    return expression


def start():
    """Start application."""
    import shutil

    data_dir = os.path.join(current_dir, 'data')
    if os.path.isdir(data_dir):
        shutil.rmtree(data_dir)
    args = [
        '--datadir={0}'.format(data_dir),
        '--nolaunch',
    ]

    os.makedirs(data_dir)
    os.chdir(data_dir)
    config = ConfigParser()
    config.read('config.ini')
    config.add_section('General')
    config.set('General', 'web_username', stash['web-username'])
    config.set('General', 'web_password', stash['web-password'])
    config.set('General', 'api_key', stash['api-key'])
    with io.open('config.ini', 'w', encoding='utf-8') as configfile:
        config.write(configfile)

    sys.path.insert(1, root_dir)

    from medusa.__main__ import Application
    application = Application()
    application.start(args)


if __name__ == '__main__':
    start()
