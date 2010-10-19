import sys

from django.db import connections, router, transaction, models, DEFAULT_DB_ALIAS
from django.db.models.loading import cache, load_app as django_load_app
from django.core.management.color import no_style
from django.core.management.sql import custom_sql_for_model, emit_post_sync_signal
from django.contrib.contenttypes.management import update_contenttypes
from django.contrib.auth.management import create_permissions

loaded_models = {}

def load_app(app_path):
    testapp = django_load_app(app_path)
    app_name = testapp.__name__.split('.')[-2]
    connection = connections[DEFAULT_DB_ALIAS]
    cursor = connection.cursor()
    test_models = [m for m in models.get_models(testapp, include_auto_created=True)
            if router.allow_syncdb(DEFAULT_DB_ALIAS, m)]
    loaded_models[app_path] = test_models
    # We assume the models haven't been installed, otherwise there's more to do here
    
    # Get a list of already installed *models* so that references work right.
    tables = connection.introspection.table_names()
    seen_models = connection.introspection.installed_models(tables)
    pending_references = {}
    
    verbosity = 0
    
    # Create the tables for each model
    for model in test_models:
        # Create the model's database table, if it doesn't already exist.
        if verbosity >= 2:
            print "Processing %s.%s model" % (app_name, model._meta.object_name)
        sql, references = connection.creation.sql_create_model(model, no_style(), seen_models)
        seen_models.add(model)
        for refto, refs in references.items():
            pending_references.setdefault(refto, []).extend(refs)
            if refto in seen_models:
                sql.extend(connection.creation.sql_for_pending_references(refto, no_style(), pending_references))
        sql.extend(connection.creation.sql_for_pending_references(model, no_style(), pending_references))
        if verbosity >= 1 and sql:
            print "Creating table %s" % model._meta.db_table
        for statement in sql:
            cursor.execute(statement)
        tables.append(connection.introspection.table_name_converter(model._meta.db_table))
    transaction.commit_unless_managed(using=DEFAULT_DB_ALIAS)
    
    for model in test_models:
        index_sql = connection.creation.sql_indexes_for_model(model, no_style())
        if index_sql:
            if verbosity >= 1:
                print "Installing index for %s.%s model" % (app_name, model._meta.object_name)
            try:
                for sql in index_sql:
                    cursor.execute(sql)
            except Exception, e:
                sys.stderr.write("Failed to install index for %s.%s model: %s\n" % \
                                    (app_name, model._meta.object_name, e))
                transaction.rollback_unless_managed(using=DEFAULT_DB_ALIAS)
            else:
                transaction.commit_unless_managed(using=DEFAULT_DB_ALIAS)
    
    # We won't bother with looking for custom SQL and fixtures, though the latter
    # should be done at some point.
    # What worries me at this point is that models.get_app('blug') fails, though
    # models.get_apps()[-1] returns the blug app.
    
    # We *could* do this:
    #emit_post_sync_signal(test_models, verbosity, 0, DEFAULT_DB_ALIAS)
    # But let's do this instead:
    update_contenttypes(testapp, test_models, verbosity)
    create_permissions(testapp, test_models, verbosity)
        

def unload_app(app_name):
    # Output DROP TABLE statements for standard application tables.
    connection = connections[DEFAULT_DB_ALIAS]
    cursor = connection.cursor()
    
    output = []
    to_delete = set()
    references_to_delete = {}
    
    table_names = connection.introspection.get_table_list(cursor)
    for model in loaded_models[app_name]:
        if cursor and connection.introspection.table_name_converter(model._meta.db_table) in table_names:
            # The table exists, so it needs to be dropped
            opts = model._meta
            for f in opts.local_fields:
                if f.rel and f.rel.to not in to_delete:
                    references_to_delete.setdefault(f.rel.to, []).append( (model, f) )
            to_delete.add(model)
    
    for model in loaded_models[app_name]:
        if connection.introspection.table_name_converter(model._meta.db_table) in table_names:
            output.extend(connection.creation.sql_destroy_model(model, references_to_delete, no_style()))
    output = output[::-1] # Reverse it, to deal with table dependencies.
    for deletion in output:
        cursor.execute(deletion)
    transaction.commit_unless_managed(using=DEFAULT_DB_ALIAS)
    
    del cache.app_store[cache.load_app(app_name)]
    
    #update_all_contenttypes()

