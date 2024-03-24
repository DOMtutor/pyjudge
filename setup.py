from setuptools import setup

setup(
    name="PyDOMjudge",
    version="0.1.0",
    author="Tobias Meggendorfer",
    author_email="tobias@meggendorfer",
    packages=[
        "pyjudge",
        "pyjudge.action",
        "pyjudge.data",
        "pyjudge.model",
        "pyjudge.repository",
        "pyjudge.scripts",
    ],
    entry_points={
        "console_scripts": [
            "dt_judge_upload=pyjudge.scripts.upload:main",
            "dt_judge_export=pyjudge.scripts.export:main",
            "dt_find=pyjudge.scripts.find_problem:main",
            "dt_check=pyjudge.scripts.check:main",
            "dt_get=pyjudge.scripts.get:main",
            "dt_generate_seed=pyjudge.scripts.generate_seed:main",
        ],
    },
    include_package_data=True,
    license="GPLv3",
    install_requires=[
        "mysql-connector-python>=8.0",
        "PyYAML>=6.0",
        "Pillow>=9.0",
        "dateutils>=0.6",
        "problemtools",
    ],
    description="A library to ease interaction with DOMjudge",
)
