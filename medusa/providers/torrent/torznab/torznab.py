# coding=utf-8

"""Provider code for Torznab provider."""

from __future__ import unicode_literals

import logging
import os
import re
from collections import namedtuple

from medusa import (
    app,
    tv,
)
from medusa.bs4_parser import BS4Parser
from medusa.helper.common import convert_size
from medusa.indexers.config import (
    INDEXER_TMDB,
    INDEXER_TVDBV2,
    INDEXER_TVMAZE,
)
from medusa.indexers.utils import mappings
from medusa.logger.adapters.style import BraceAdapter
from medusa.providers.generic_provider import GenericProvider
from medusa.providers.torrent.torrent_provider import TorrentProvider

from requests.compat import urljoin

from six import iteritems, itervalues, text_type as str


log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())

INDEXERS_PARAM = {INDEXER_TVDBV2: 'tvdbid', INDEXER_TVMAZE: 'tvmazeid', INDEXER_TMDB: 'tmdbid'}


class TorznabProvider(TorrentProvider):
    """Generic provider for built in and custom providers who expose a Torznab compatible api."""

    def __init__(self, name, url=None, api_key=None, cat_ids=None, cap_tv_search=None,
                 search_mode='eponly', search_fallback=False, enable_daily=True,
                 enable_backlog=False, enable_manualsearch=False, manager=None, search_timeout=30):
        """Initialize the class."""
        super(TorznabProvider, self).__init__(name)

        self.provider_sub_type = GenericProvider.TORZNAB

        self.url = url or ''
        self.api_key = api_key or ''
        self.cat_ids = cat_ids or ['5010', '5030', '5040', '7000']
        self.cap_tv_search = cap_tv_search or []
        self.search_mode = search_mode
        self.search_fallback = search_fallback
        self.enable_daily = enable_daily
        self.enable_backlog = enable_backlog
        self.enable_manualsearch = enable_manualsearch
        self.search_timeout = self.normalize_search_timeout(search_timeout)

        # For now apply the additional season search string for all torznab providers.
        # If we want to limited this per provider, I suggest using a dict, with provider: [list of season templates]
        # construction.
        self.season_templates = (
            'S{season:0>2}',  # example: 'Series.Name S03'
            'Season {season}',  # example: 'Series.Name Season 3'
        )

        # Proper Strings
        self.proper_strings = ['PROPER', 'REPACK', 'REAL', 'RERIP']

        # Specify the manager if externally managed.
        self.manager = manager
        self.id_manager = self.name

        self.cache = tv.Cache(self)

    @staticmethod
    def normalize_search_timeout(value):
        """Bound Torznab response timeouts without affecting other providers."""
        try:
            timeout = int(value)
        except (TypeError, ValueError, OverflowError):
            return 30
        return max(30, min(timeout, 600))

    def _cap_tv_params(self):
        """Return Torznab tv-search capability params as a set."""
        return {param for param in (self.cap_tv_search or []) if param}

    def _supports_structured_tv_text_search(self):
        """Whether caps allow Sonarr-like tvsearch with q + season (+ optional ep)."""
        caps = self._cap_tv_params()
        return 'q' in caps and 'season' in caps

    def _apply_season_episode_params(self, search_params, ep_obj, mode):
        """Attach season/ep params from the episode, matching Torznab/Sonarr conventions."""
        if not ep_obj:
            return

        if ep_obj.series.air_by_date or ep_obj.series.sports:
            date_str = str(ep_obj.airdate)
            search_params['season'] = date_str.partition('-')[0]
            search_params['ep'] = date_str.partition('-')[2].replace('-', '/')
        else:
            search_params['season'] = ep_obj.scene_season
            search_params['ep'] = ep_obj.scene_episode

        if mode == 'Season':
            search_params.pop('ep', None)

    @staticmethod
    def _title_query_from_search_string(search_string):
        """Strip episode/season markers so Torznab ``q`` is a show title."""
        title = search_string.strip()
        patterns = (
            r'[\s._-]+S\d{1,4}[\s._-]*E\d{1,4}(?:[\s._-]*E\d{1,4})?.*$',
            r'[\s._-]+\d{1,4}[xX]\d{1,4}.*$',
            r'[\s._-]+(?:Season|Saison)[\s._-]*\d+.*$',
            r'[\s._-]+S\d{1,4}$',
            r'[\s._-]+\d{4}[\s._-]\d{2}[\s._-]\d{2}.*$',
            r'[\s._-]+\d{4}[\s._-]\d{2}/\d{2}.*$',
        )
        for pattern in patterns:
            title = re.sub(pattern, '', title, flags=re.IGNORECASE)
        return title.replace('.', ' ').replace('_', ' ').strip()

    def _structured_tv_title_queries(self, search_strings, mode, ep_obj):
        """Build title-only queries for structured tvsearch (Sonarr-like)."""
        titles = []
        if ep_obj and getattr(ep_obj, 'series', None):
            names = ep_obj.series.get_all_possible_names()
            if ep_obj.scene_season is not None:
                names = names.union(ep_obj.series.get_all_possible_names(season=ep_obj.scene_season))
            titles = sorted(name for name in names if name)

        if titles:
            return titles

        return [
            self._title_query_from_search_string(search_string)
            for search_string in search_strings.get(mode, [])
            if search_string
        ]

    def search(self, search_strings, age=0, ep_obj=None, force_query=False, manual_search=False, **kwargs):
        """
        Search a provider and parse the results.

        :param search_strings: A dict with mode (key) and the search value (value)
        :param age: Not used
        :param ep_obj: Episode object used for season/ep Torznab params
        :param force_query: Skip indexer-ID tvsearch and force a text query. When the
            provider caps support ``q``+``season``, use Sonarr-like ``tvsearch`` with a
            title query; otherwise fall back to free-text ``t=search``.
        :param manual_search: If the search is started through a manual search, we're utilizing the force_query param.
        :returns: A list of search results (structure)
        """
        results = []
        if not self._check_auth():
            return results

        # Keep caps fresh for indexers like aMuTorrent that advertise q,season,ep only.
        if not self.cap_tv_search:
            self.get_capabilities(just_params=True)

        # Search Params
        search_params = {
            'apikey': self.api_key,
            't': 'search',
            'limit': 100,
            'offset': 0,
            'cat': ','.join(self.cat_ids),
        }

        used_id_tvsearch = False

        for mode in search_strings:
            log.debug('Search mode: {0}', mode)

            match_indexer = {}
            use_id_search = False
            use_structured_text = False
            query_values = search_strings[mode]

            if mode != 'RSS':
                match_indexer = self._match_indexer()
                use_id_search = bool(match_indexer) and not force_query
                use_structured_text = (
                    not use_id_search
                    and self._supports_structured_tv_text_search()
                    and ep_obj is not None
                )

                if use_id_search:
                    search_params['t'] = 'tvsearch'
                    search_params.update(match_indexer)
                    self._apply_season_episode_params(search_params, ep_obj, mode)
                    used_id_tvsearch = True
                elif use_structured_text:
                    search_params['t'] = 'tvsearch'
                    search_params.pop('q', None)
                    for indexer_param in itervalues(INDEXERS_PARAM):
                        search_params.pop(indexer_param, None)
                    self._apply_season_episode_params(search_params, ep_obj, mode)
                    query_values = self._structured_tv_title_queries(search_strings, mode, ep_obj)
                else:
                    search_params['t'] = 'search'
                    search_params.pop('season', None)
                    search_params.pop('ep', None)
                    for indexer_param in itervalues(INDEXERS_PARAM):
                        search_params.pop(indexer_param, None)

            for search_string in query_values:
                active_params = dict(search_params)

                if mode != 'RSS':
                    # PROPER/REPACK searches stay free-text so the keyword remains in q.
                    if any(proper_string in search_string
                           for proper_string in self.proper_strings):
                        active_params = {
                            'apikey': self.api_key,
                            't': 'search',
                            'limit': 100,
                            'offset': 0,
                            'cat': ','.join(self.cat_ids),
                            'q': search_string,
                        }
                    elif active_params['t'] == 'tvsearch' and use_id_search:
                        pass
                    elif active_params['t'] == 'tvsearch':
                        active_params['q'] = (
                            search_string
                            if use_structured_text
                            else self._title_query_from_search_string(search_string)
                        )
                    else:
                        active_params['q'] = search_string

                    if active_params['t'] == 'tvsearch' and use_id_search:
                        search_desc = 'indexer_id: {0}'.format(match_indexer)
                    elif active_params['t'] == 'tvsearch':
                        search_desc = 'tvsearch q={q!r} season={season!r} ep={ep!r}'.format(
                            q=active_params.get('q'),
                            season=active_params.get('season'),
                            ep=active_params.get('ep'),
                        )
                    else:
                        search_desc = 'search string: {0}'.format(active_params.get('q', search_string))

                    log.debug('Search show using {search}', {'search': search_desc})

                response = self.session.get(
                    urljoin(self.url, 'api'),
                    params=active_params,
                    timeout=(30, self.normalize_search_timeout(self.search_timeout)),
                )
                if not response or not response.text:
                    log.debug('No data returned from provider')
                    continue

                results += self.parse(response.text, mode)

                # ID-based tvsearch does not vary by search string.
                if use_id_search and any(param in active_params for param in itervalues(INDEXERS_PARAM)):
                    break

        # After a failed ID tvsearch, retry with text query (structured when caps allow).
        if not results and used_id_tvsearch and not force_query:
            return self.search(search_strings, ep_obj=ep_obj, force_query=True)

        return results

    def parse(self, data, mode):
        """
        Parse search results for items.

        :param data: The raw response from a search
        :param mode: The current mode used to search, e.g. RSS

        :return: A list of items found
        """
        items = []

        with BS4Parser(data, 'html5lib') as html:

            rows = html('item')
            if not rows:
                log.debug(
                    'No results returned from provider. Check chosen Torznab search categories '
                    'in provider settings.')
                return items

            for item in rows:
                try:
                    title = item.title.get_text(strip=True)
                    download_url = item.enclosure.get('url')
                    if not all([title, download_url]):
                        continue

                    seeders_attr = item.find('torznab:attr', attrs={'name': 'seeders'})
                    peers_attr = item.find('torznab:attr', attrs={'name': 'peers'})
                    seeders = int(seeders_attr.get('value', 0)) if seeders_attr else 1
                    peers = int(peers_attr.get('value', 0)) if peers_attr else 0
                    leechers = peers - seeders if peers - seeders > 0 else 0

                    # Filter unseeded torrent
                    if seeders < self.minseed:
                        if mode != 'RSS':
                            log.debug("Discarding torrent because it doesn't meet the"
                                      ' minimum seeders: {0}. Seeders: {1}',
                                      title, seeders)
                        continue

                    torrent_size = item.find('torznab:attr', attrs={'name': 'size'})
                    if torrent_size:
                        torrent_size = torrent_size.get('value')

                    if not torrent_size:
                        torrent_size = item.size.get_text(strip=True)
                    size = convert_size(torrent_size, default=-1)

                    pubdate_raw = item.pubdate.get_text(strip=True)
                    pubdate = self.parse_pubdate(pubdate_raw)

                    item = {
                        'title': title,
                        'link': download_url,
                        'size': size,
                        'seeders': seeders,
                        'leechers': leechers,
                        'pubdate': pubdate,
                    }
                    if mode != 'RSS':
                        log.debug('Found result: {0} with {1} seeders and {2} leechers',
                                  title, seeders, leechers)

                    items.append(item)
                except (AttributeError, TypeError, KeyError, ValueError, IndexError):
                    log.exception('Failed parsing provider.')

        return items

    def _check_auth(self):
        """
        Check that user has set their api key if it is needed.

        :return: True/False
        """
        if not self.api_key:
            log.warning('Invalid api key. Check your settings')
            return False

        return True

    @staticmethod
    def get_providers_list(providers):
        """Return custom rss torrent providers."""
        return [TorznabProvider(custom_provider) for custom_provider in providers]

    @staticmethod
    def _get_identifier(item):
        """
        Return the identifier for the item.

        By default this is the url. Providers can overwrite this, when needed.
        """
        return '{name}_{size}'.format(name=item.name, size=item.size)

    def image_name(self):
        """
        Check if we have an image for this provider already.

        Returns found image or the default Torznab image
        """
        if os.path.isfile(os.path.join(app.THEME_DATA_ROOT, 'assets/img/providers/', self.get_id() + '.png')):
            return self.get_id() + '.png'

        if self.manager == 'prowlarr':
            return 'prowlarr.png'

        return 'jackett.png'

    def _match_indexer(self):
        """Use the indexers id and externals, and return the most optimal indexer with value.

        For torznab providers we prefer to use tvdb for searches, but if this is not available for shows that have
        been indexed using an alternative indexer, we could also try other indexers id's that are available
        and supported by this torznab provider.
        """
        indexer_mapping = {}

        if not self.series:
            return indexer_mapping

        supported_params = self.cap_tv_search
        if not supported_params:
            # We didn't get back any supportedParams, lets return
            # and continue with doing a search string search.
            return indexer_mapping

        indexer_params = ((x, v) for x, v in iteritems(INDEXERS_PARAM) if v in supported_params)
        for indexer, indexer_param in indexer_params:
            # We have a direct match on the indexer used, no need to try the externals.
            if self.series.indexer == indexer:
                indexer_mapping[indexer_param] = self.series.indexerid
                break

            # No direct match, let's see if one of the externals provides a valid indexer_param.
            external_indexerid = self.series.externals.get(mappings[indexer])
            if external_indexerid:
                indexer_mapping[indexer_param] = external_indexerid
                break

        return indexer_mapping

    def set_caps(self, data):
        """Set caps."""
        if not data:
            return

        def _parse_cap(tag):
            elm = data.find(tag)
            is_supported = elm and all([elm.get('supportedparams'), elm.get('available') == 'yes'])
            return elm['supportedparams'].split(',') if is_supported else []

        self.cap_tv_search = _parse_cap('tv-search')

    def get_capabilities(self, just_params=False):
        """
        Use the provider url and apikey to get the capabilities.

        Makes use of the default torznab caps param. e.a. http://yourznab/api?t=caps&apikey=skdfiw7823sdkdsfjsfk
        Returns a tuple with (succes or not, array with dicts [{'id': '5070', 'name': 'Anime'},
        {'id': '5080', 'name': 'Documentary'}, {'id': '5020', 'name': 'Foreign'}...etc}], error message)
        """
        Capabilities = namedtuple('Capabilities', 'success categories params message')
        categories = params = []

        if not self._check_auth():
            message = 'Provider requires auth and your key is not set'
            return Capabilities(False, categories, params, message)

        url_params = {'t': 'caps', 'apikey': self.api_key}

        response = self.session.get(urljoin(self.url, 'api'), params=url_params)
        if not response or not response.text:
            message = 'Error getting caps xml for: {0}'.format(self.name)
            log.warning(message)
            return Capabilities(False, categories, params, message)

        with BS4Parser(response.text, 'html5lib') as html:
            if not html.find('categories'):
                message = 'Error parsing caps xml for: {0}'.format(self.name)
                log.warning(message)
                return Capabilities(False, categories, params, message)

            self.set_caps(html.find('searching'))
            params = self.cap_tv_search
            if just_params:
                message = 'Success getting params for: {0}'.format(self.name)
                return Capabilities(True, categories, params, message)

            for category in html('category'):
                if 'TV' in category.get('name', '') and category.get('id'):
                    categories.append({'id': category['id'], 'name': category['name']})
                    for subcat in category('subcat'):
                        if 'TV' in subcat.get('name', '') and subcat.get('id'):
                            categories.append({'id': subcat['id'], 'name': subcat['name']})

            message = 'Success getting categories and params for: {0}'.format(self.name)
            return Capabilities(True, categories, params, message)
