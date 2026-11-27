# coding=utf-8
"""Use setup tools to install Medusa."""
import io
import os
import re
import sys

from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))


def get_app_version():
    """Get the app version from the code."""
    pattern = re.compile(r"VERSION = '([0-9.]+)'")
    filename = os.path.join(here, 'medusa', 'common.py')
    with io.open(filename, 'r', encoding='utf-8') as fh:
        for line in fh:
            match = pattern.match(line)
            if match:
                return match.group(1)

    raise ValueError('Failed to get the app version!')


with open(os.path.join(here, 'README.md'), encoding='utf-8') as readme_file:
    long_description = readme_file.read()


def packages():
    result = []

    for folder in ('medusa', 'ext', 'lib', 'themes'):
        if os.path.isdir(os.path.join(here, folder)):
            result.append(folder)

    for folder in ('ext2', 'ext3', 'lib2', 'lib3'):
        if os.path.isdir(os.path.join(here, folder)) and sys.version_info.major == int(folder[-1]):
            result.append(folder)

    return result


setup(
    name='pymedusa',
    description='Automatic Video Library Manager for TV Shows',
    version=get_app_version(),
    author='pymedusa team',
    author_email='',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/pymedusa/Medusa',
    license='GPLv3',
    python_requires='>=3.10',
    packages=packages(),
    include_package_data=True,
    # install_requires=install_requires(),
    extras_require={
        'system-stats': ['psutil'],
    },
    entry_points={
        'console_scripts': [
            'medusa = medusa.__main__:main'
        ]
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: End Users/Desktop',
        'Intended Audience :: Developers',
        'Operating System :: MacOS',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: Unix',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
        'Programming Language :: Python :: Implementation :: CPython',
        'Topic :: Internet',
        'Topic :: Multimedia :: Video',
    ],
)
