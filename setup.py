from setuptools import setup

setup(
  name='PyDOMjudge',
  # version='0.1.0',
  author='Tobias Meggendorfer',
  author_email='tobias@meggendorfer',
  packages=['pyjudge', 'pyjudge.action', 'pyjudge.data', 'pyjudge.model'],
  scripts=[],
  # license='LICENSE.txt',
  install_requires=[
    'mysql-connector-python>=8.0'
  ],
  description='A library to ease interaction with DOMjudge',
)
