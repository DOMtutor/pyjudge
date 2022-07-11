from setuptools import setup

setup(
  name='PyDOMjudge',
  # version='0.1.0',
  author='Tobias Meggendorfer',
  author_email='tobias@meggendorfer',
  packages=['pyjudge', 'pyjudge.action', 'pyjudge.data', 'pyjudge.model', 'pyjudge.repository'],
  entry_points={
    'console_scripts': [
      'judge_upload=pyjudge.scripts.upload:main',
      'judge_export=pyjudge.scripts.export:main',
      'find_problem=pyjudge.scripts.find_problem:main'
    ],
  },
  # license='LICENSE.txt',
  install_requires=[
    'mysql-connector-python>=8.0'
  ],
  description='A library to ease interaction with DOMjudge',
)
