from setuptools import setup


setup(
    entry_points={
        "console_scripts": [
            "matrixs=matrixs.cli:main",
            "software=software_sdk.cli:main",
        ],
    }
)
