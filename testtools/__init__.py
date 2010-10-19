import sys
from copy import copy
from operator import add
from random import sample
from string import ascii_letters

from django import template
from django.contrib.auth.models import User
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.urlresolvers import clear_url_caches
from django.db.models.loading import load_app as django_load_app
from django.test import TestCase
from django.template.loaders import app_directories
from django.template import loader

from apploader import unload_app, load_app as apploader_load_app 

class UniqueNameGenerator(list):
    pass # TODO:

class UserGenerator():
    def __init__(self):
        self._items = {}
    
    def __getitem__(self, index):
        if not index in self._items:
            username = None
            while not username or username in [user['username'] for user in self._items.values()]:
                username = reduce(add, sample(ascii_letters, 10))
            new_user = {
                'username': username,
                'password': reduce(add, sample(ascii_letters, 8)),
                'email': '%s@example.com' % username,
                }
            self._items[index] = new_user
        return self._items[index]

class TestSettings(object):
    def __init__(self):
        # Since we're overriding getattribute, any actual properties for the
        # class need to be accessed through "object".
        object.__setattr__(self, '_original_settings', {})
    
    def __setattr__(self, attr, value):
        original_settings = object.__getattribute__(self, '_original_settings')
        if attr not in original_settings:
            if hasattr(settings, attr):
                original_settings[attr] = {'in_original': True, 'values': [getattr(settings, attr),]} 
            else:
                original_settings[attr] = {'in_original': False, 'values': [attr,]}
        else:
            # If settings has already been modified, add new value to stack
            original_settings[attr][1].append(value)
        setattr(settings, attr, value)
    
    def __getattribute__(self, attr):
        return getattr(settings, attr)
    
    def restore(self, attr, to_original=False):
        original_settings = object.__getattribute__(self, '_original_settings')
        if attr in original_settings:
            assert original_settings[attr]['values']
            if to_original or len(original_settings[attr]['values']) == 1:
                if not original_settings[attr]['in_original']:
                    delattr(settings, attr)
                else:
                    setattr(settings, attr, original_settings[attr]['values'][0])
                del original_settings[attr]
            else:
                setattr(settings, attr, original_settings[attr]['values'].pop(-1))
        else:
            raise ValueError('The attribute %s was never set.' % attr)
     
    def restore_all(self):
        for attr in object.__getattribute__(self, '_original_settings').keys():
            object.__getattribute__(self, 'restore')(attr, to_original=True)


class TestToolkit(TestCase):
    # The module of a test app to load for testing purposes. The urls from
    # the test_app will be used automatically, unless overridden in the
    # urls property.
    test_app = ''
    # A dictonary of settings to override for the duration of the tests.
    settings_override = {}
    # Specifies whether templates in project/templates should be used.
    use_project_templates = False
    # Specifies whether the test app should only be loaded for the duration
    # of running the tests for the current module. This offers the advantage
    # of avoiding potential conflicts with other apps in the project, but may
    # not work as smoothly. Note that when using non-localised app loading,
    # the app's urls will not be globally available.
    localise_app_loading = True
    # Specified whether the project URLs should be available during testing.
    # The test-specific URLs will be appended to the start of the available
    # urpatterns.
    include_project_urls = False
    
    _creation_counter = 0
    _creation_counters = {}
    _loaded_apps = []
    _original_urls = []
    
    def __init__(self, *args, **kwargs):
        super(TestToolkit, self).__init__(*args, **kwargs)
        self.names = UniqueNameGenerator()
        self.settings = TestSettings()
        self.users = UserGenerator()
        self._test_app_loaded = False
        
        if self._get_module() in TestToolkit._creation_counters:
            TestToolkit._creation_counters[self._get_module()] += 1
        else:
            TestToolkit._creation_counters[self._get_module()] = 0
        self._creation_counter = TestToolkit._creation_counters[self._get_module()]
        
        if hasattr(self.__class__, 'urls') and self.include_project_urls:
            # Prevent TestCase from finding the urls attribute
            self.__class__._urls = self.__class__.urls
            delattr(self.__class__, 'urls')
        
        if not self.localise_app_loading:
            # Use Django's built-in app loading
            self.load_app(self.test_app, use_django=True)
    
    def restore_setting(self, setting, to_original=False):
        """
        Restore a single setting to its previous value.
        
        setting     -- The setting to restore.
        to_original -- Whether to revert the settings to its original value
                       or just revert the last change.
        """
        object.__getattribute__(self.settings, 'restore')(setting, to_original)
    
    def restore_all_settings(self):
        """Restore all modified settings to their original values."""
        object.__getattribute__(self.settings, 'restore_all')()
    
    def setUp(self):
        # Load settings from the settings_override property.
        for k, v in self.settings_override.items():
            setattr(self.settings, k, v)
        # Disable template loading from project/templates.
        if not self.use_project_templates:
            loaders = list(self.settings.TEMPLATE_LOADERS)
            try:
                loaders.remove('django.template.loaders.filesystem.Loader')
                self.settings.TEMPLATE_LOADERS = loaders
                self._refresh_cache()
            except ValueError:
                pass
        # Check if this is the first set-up for this module.
        if self._creation_counter == 0:
            if self.localise_app_loading:
                self.load_app(self.test_app)
            if hasattr(self.__class__, '_urls'):
                self.load_urls(self.__class__._urls, self.include_project_urls)
            self.setUpModule()
    
    def tearDown(self):
        # Check if this is the last tear-down for this module
        if self._creation_counter == TestToolkit._creation_counters.get(self._get_module(), None):
            self.tearDownModule()
            if self.localise_app_loading:
                self.unload_app(self.test_app)
            if hasattr(self.__class__, '_urls'):
                self.unload_urls(to_original=True)
#            if not self.use_project_templates:
#                reload(app_directories)
        self.restore_all_settings()
    
    def setUpModule(self):
        """
        An overrideable convenience method called immediately before the first
        test in the current module is executed. A super() call is not required.
        """
        pass
    
    def tearDownModule(self):
        """
        An overrideable convenience method called after the last test in the
        current module is executed. A super() call is not required.
        """
        pass
    
    def load_app(self, app, use_django=False):
        """
        Load a new Django app into the project.
        
        app        -- the module name string of the app to load.
        use_django -- if set to True, Django's built-in load_app function will
                      be used. This should only be done before any syncdb
                      calls have been issued, otherwise the models will not
                      have DB tables.
        """
        if not app or app in TestToolkit._loaded_apps:
            return
        TestToolkit._loaded_apps.append(app)
        
        # In case the new app will be overriding templates, make sure it
        # appears before the current app in INSTALLED_APPS
        installed_apps = list(settings.INSTALLED_APPS)
        try:
            # Find the best matching app name for the current module
            app_name = sorted(
                filter(
                    lambda x: self.__module__.startswith(x),
                    settings.INSTALLED_APPS
                    ),
                lambda x,y: len(y).__cmp__(len(x))
                )[0]
            # Insert new app before the current app in INSTALLED_APPS
            installed_apps.insert(installed_apps.index(app_name), app)
        except IndexError:
            # Current app not found, append new app to the end
            installed_apps.append(app)
        settings.INSTALLED_APPS = installed_apps
        
        # Load the app
        if use_django:
            django_load_app(app)
        else:
            apploader_load_app(app)
        
        # Check if app has a valid urls module and store it in the class's
        # _urls property, if it is not set already
        if not hasattr(self.__class__, '_urls') and not hasattr(self.__class__, 'urls'):
            url_module = '%s.urls' % app
            try:
                __import__(url_module)
                if hasattr(sys.modules[url_module], 'urlpatterns'):
                    self.__class__._urls = url_module
            except ImportError:
                # If the app doesn't have a urls module, no need to load it
                pass
        
        self._refresh_cache()
    
    def unload_app(self, app):
        """Unload an app loaded by TestToolkit from the project."""
        if not app or app not in TestToolkit._loaded_apps:
            return
        TestToolkit._loaded_apps.remove(app)
        
        # Remove app from INSTALLED_APPS
        installed_apps = list(settings.INSTALLED_APPS)
        installed_apps.remove(app)
        settings.INSTALLED_APPS = installed_apps
        
        unload_app(app)
        
        self._refresh_cache()
    
    def load_urls(self, urls, append_to_existing):
        # Get the url module to be loaded
        __import__(urls)
        url_module = sys.modules[urls]
        # Get the url module currently used by the project
        __import__(self.settings.ROOT_URLCONF)
        project_url_module = sys.modules[self.settings.ROOT_URLCONF]
        # Store a copy for restoring later
        self.__class__._original_urls.append(copy(project_url_module.urlpatterns))
        if append_to_existing:
            project_url_module.urlpatterns = url_module.urlpatterns + project_url_module.urlpatterns
        else:
            project_url_module.urlpatterns = url_module.urlpatterns
        clear_url_caches()
    
    def unload_urls(self, to_original=False):
        __import__(self.settings.ROOT_URLCONF)
        project_url_module = sys.modules[self.settings.ROOT_URLCONF]
        while self.__class__._original_urls:
            project_url_module.urlpatterns = self.__class__._original_urls.pop()
            if not to_original:
                break
        clear_url_caches()
    
    def _refresh_cache(self):
        """Refresh the template and templatetags cache after (un)loading an app."""
        # Reload the module to refresh the template cache
        reload(app_directories)
        loader.template_source_loaders = None
        
        # Since django's r11862 templatags_modules and app_template_dirs are
        # cached, the cache is not emptied between tests. Clear out the cache
        # of modules to load templatetags from so it gets refreshed
        if hasattr(template, 'templatetags_modules'):
            template.templatetags_modules = []

    def _get_module(self):
        """Returns the part of the current module name before '.tests'."""
        if '.tests' in self.__module__:
            return self.__module__[:self.__module__.index('.tests')]
        return self.__module__

    def create_test_user(self, username='testuser', password='apass', email='test@test.com', status='staff'):
        """Create a test user and log them in to the site."""
        new_user = User.objects.create_user(username=username, email=email, password=password)
        if status in ['staff', 'superuser']:
            new_user.is_staff = True
            if status == 'superuser':
                new_user.is_superuser = True
            new_user.save()
        login = self.client.login( username=username, password=password )
        self.assertTrue(login)   
        return new_user
        
