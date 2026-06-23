from setuptools import setup


setup(
    entry_points={
        "console_scripts": [
            "software=software_sdk.cli:main",
        ],
    }
)
