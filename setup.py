from setuptools import setup, find_packages

setup(
    name="yandex-market-private-api",
    version="0.2.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[],
    extras_require={
        "fast": ["brotli>=1.0.9", "curl_cffi>=0.7.0"],
        "crypto": ["cryptography>=41.0.0"],
        "full": ["brotli>=1.0.9", "curl_cffi>=0.7.0", "cryptography>=41.0.0"],
    },
)
