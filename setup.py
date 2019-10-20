"""Install the ``entangler`` package for use in ARTIQ.

You can install this package locally (in development mode) using:
``$ pip install -e .``.
"""
from setuptools import find_packages
from setuptools import setup

if __name__ == "__main__":
    setup(
        name="entangler",
        version="0.1",
        packages=find_packages(),
        requirements=["migen"],
        url="https://github.com/OxfordIonTrapGroup/entangler-core",
        setup_requires=["pytest-runner"],
        tests_require=["pytest"],
    )
