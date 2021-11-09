from setuptools import setup

setup(
  name='PyJudge',
  version='0.1.0',
  author='Tobias Meggendorfer',
  author_email='tobias@meggendorfer',
  packages=['pyjudge', 'pyjudge.action', 'pyjudge.data', 'pyjudge.model'],
  scripts=[],
  # url='http://pypi.python.org/pypi/PackageName/',
  # license='LICENSE.txt',
  description='A library to ease interaction with DOMjudge',
  # long_description=open('README.txt').read(),
  # install_requires=[
  #     "Django >= 1.1.1",
  #     "pytest",
  # ],
)
