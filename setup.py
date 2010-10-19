#!/usr/bin/env python
# -*- coding: utf-8 -*-

from distutils.core import setup

setup(
    name='glamkit-testtools',
    version='0.1',
    description='Improvements for the Django testing framework.',
    author='The Interaction Consortium',
    author_email='admins@interaction.net.au',
    #url='http://',
    packages=['testtools',],
    license='BSD',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Utilities'
    ],
)
