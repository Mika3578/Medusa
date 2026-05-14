import Vuex, { Store } from 'vuex';
import VueRouter from 'vue-router';
import { createLocalVue, mount } from '@vue/test-utils';
import { NewShow } from '../../src/components';
import fixtures from '../__fixtures__/common';

describe('NewShow language handling for existing shows', () => {
    let localVue;
    let store;
    let mockClient;
    let mockSnotify;
    let mockRouter;

    beforeEach(() => {
        localVue = createLocalVue();
        localVue.use(Vuex);
        localVue.use(VueRouter);

        // Create a mock API client
        mockClient = {
            api: {
                post: jest.fn()
            }
        };

        // Create mock snotify
        mockSnotify = {
            warning: jest.fn(),
            error: jest.fn(),
            success: jest.fn()
        };

        // Create mock router
        mockRouter = new VueRouter({
            routes: [
                { path: '/add-new-show', name: 'addNewShow' },
                { path: '/home', name: 'home' }
            ]
        });

        const { state } = fixtures;
        // Set Spanish as the default language for testing
        const testState = {
            ...state,
            config: {
                ...state.config,
                general: {
                    ...state.config.general,
                    indexerDefaultLanguage: 'es'
                }
            },
            auth: {
                client: mockClient
            }
        };

        store = new Store({
            state: testState,
            getters: {
                indexerIdToName: () => id => {
                    const indexerMap = { 1: 'tvdb', 2: 'tvmaze', 3: 'tmdb' };
                    return indexerMap[id] || 'unknown';
                }
            }
        });
    });

    it('uses indexerDefaultLanguage when providedInfo.indexerLanguage is null', async () => {
        const wrapper = mount(NewShow, {
            localVue,
            store,
            router: mockRouter,
            mocks: {
                $snotify: mockSnotify,
                $modal: {
                    show: jest.fn()
                }
            },
            stubs: [
                'vue-tabs',
                'v-tab',
                'form-wizard',
                'tab-content',
                'new-show-search',
                'root-dirs',
                'add-show-options',
                'modal'
            ],
            propsData: {
                providedInfo: {
                    use: true,
                    showId: 12345,
                    showName: 'Test Show',
                    showDir: '/path/to/show',
                    indexerId: 1,
                    indexerLanguage: null, // Null language should fall back to default
                    unattended: false
                }
            }
        });

        // Mock the response
        mockClient.api.post.mockResolvedValue({
            data: { success: true }
        });

        // Call submitForm
        await wrapper.vm.submitForm();

        // Check that the API was called with Spanish language
        expect(mockClient.api.post).toHaveBeenCalledWith(
            'series',
            expect.objectContaining({
                options: expect.objectContaining({
                    language: 'es'
                })
            }),
            expect.any(Object)
        );
    });

    it('uses providedInfo.indexerLanguage when it is provided', async () => {
        const wrapper = mount(NewShow, {
            localVue,
            store,
            router: mockRouter,
            mocks: {
                $snotify: mockSnotify,
                $modal: {
                    show: jest.fn()
                }
            },
            stubs: [
                'vue-tabs',
                'v-tab',
                'form-wizard',
                'tab-content',
                'new-show-search',
                'root-dirs',
                'add-show-options',
                'modal'
            ],
            propsData: {
                providedInfo: {
                    use: true,
                    showId: 12345,
                    showName: 'Test Show',
                    showDir: '/path/to/show',
                    indexerId: 1,
                    indexerLanguage: 'fr', // French should be used
                    unattended: false
                }
            }
        });

        // Mock the response
        mockClient.api.post.mockResolvedValue({
            data: { success: true }
        });

        // Call submitForm
        await wrapper.vm.submitForm();

        // Check that the API was called with French language
        expect(mockClient.api.post).toHaveBeenCalledWith(
            'series',
            expect.objectContaining({
                options: expect.objectContaining({
                    language: 'fr'
                })
            }),
            expect.any(Object)
        );
    });

    it('uses configured language for existing shows with metadata', async () => {
        const wrapper = mount(NewShow, {
            localVue,
            store,
            router: mockRouter,
            mocks: {
                $snotify: mockSnotify,
                $modal: {
                    show: jest.fn()
                }
            },
            stubs: [
                'vue-tabs',
                'v-tab',
                'form-wizard',
                'tab-content',
                'new-show-search',
                'root-dirs',
                'add-show-options',
                'modal'
            ],
            propsData: {
                providedInfo: {
                    use: true,
                    showId: 67890,
                    showName: 'Another Test Show',
                    showDir: '/path/to/another/show',
                    indexerId: 2,
                    indexerLanguage: 'es', // Should use Spanish, not hardcoded 'en'
                    unattended: true
                }
            }
        });

        // Mock the response
        mockClient.api.post.mockResolvedValue({
            data: { success: true }
        });

        // Call submitForm (would be called automatically with unattended: true)
        await wrapper.vm.submitForm();

        // Check that the API was called with the configured language (Spanish)
        expect(mockClient.api.post).toHaveBeenCalledWith(
            'series',
            expect.objectContaining({
                options: expect.objectContaining({
                    language: 'es'
                })
            }),
            expect.any(Object)
        );

        // Ensure 'en' was NOT used
        expect(mockClient.api.post).not.toHaveBeenCalledWith(
            'series',
            expect.objectContaining({
                options: expect.objectContaining({
                    language: 'en'
                })
            }),
            expect.any(Object)
        );
    });
});
