import Vuex, { Store } from 'vuex';
import VueRouter from 'vue-router';
import { createLocalVue, shallowMount } from '@vue/test-utils';
import { NewShow } from '../../src/components';
import fixtures from '../__fixtures__/common';

describe('NewShow.test.js', () => {
    let localVue;
    let store;
    let mockPost;

    const buildStore = indexerDefaultLanguage => {
        const { state } = fixtures;
        mockPost = jest.fn().mockResolvedValue({ data: {} });

        return new Store({
            state: {
                config: {
                    general: {
                        ...state.config.general,
                        indexerDefaultLanguage
                    },
                    indexers: state.config.indexers
                },
                auth: {
                    client: {
                        api: { post: mockPost }
                    }
                },
                shows: { queueitems: [] }
            },
            getters: {
                indexerIdToName: state => indexerId => {
                    if (!indexerId) {
                        return undefined;
                    }

                    const { indexers } = state.config.indexers;
                    return Object.keys(indexers).find(name => indexers[name].id === Number.parseInt(indexerId, 10));
                }
            }
        });
    };

    const mountNewShow = (mountStore, propsData) => shallowMount(NewShow, {
        localVue,
        store: mountStore,
        stubs: [
            'form-wizard',
            'tab-content',
            'new-show-search',
            'root-dirs',
            'add-show-options',
            'vue-tabs',
            'v-tab',
            'modal'
        ],
        mocks: {
            $snotify: { warning: jest.fn(), error: jest.fn() }
        },
        propsData
    });

    beforeEach(() => {
        localVue = createLocalVue();
        localVue.use(Vuex);
        localVue.use(VueRouter);
        store = buildStore('es');
        jest.useFakeTimers();
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    describe('submitForm with existing show (providedInfo.use = true)', () => {
        const existingShowProvidedInfo = {
            use: true,
            showId: 12345,
            showName: 'Test Show',
            showDir: '/media/TV/Test Show',
            indexerId: 1,
            indexerLanguage: null,
            unattended: false
        };

        it('uses general.indexerDefaultLanguage when providedInfo.indexerLanguage is null', async () => {
            const wrapper = mountNewShow(store, { providedInfo: { ...existingShowProvidedInfo } });

            await wrapper.vm.submitForm();

            expect(mockPost).toHaveBeenCalledTimes(1);
            const [, payload] = mockPost.mock.calls[0];
            expect(payload.options.language).toBe('es');
        });

        it('uses general.indexerDefaultLanguage from store, not hardcoded en', async () => {
            const frStore = buildStore('fr');
            const wrapper = mountNewShow(frStore, { providedInfo: { ...existingShowProvidedInfo } });

            await wrapper.vm.submitForm();

            expect(mockPost).toHaveBeenCalledTimes(1);
            const [, payload] = mockPost.mock.calls[0];
            expect(payload.options.language).toBe('fr');
            expect(payload.options.language).not.toBe('en');
        });

        it('uses providedInfo.indexerLanguage when set, ignoring store default', async () => {
            const wrapper = mountNewShow(store, {
                providedInfo: {
                    ...existingShowProvidedInfo,
                    indexerLanguage: 'de'
                }
            });

            await wrapper.vm.submitForm();

            expect(mockPost).toHaveBeenCalledTimes(1);
            const [, payload] = mockPost.mock.calls[0];
            expect(payload.options.language).toBe('de');
        });
    });
});
