from setuptools import setup, find_packages

setup(
    name="wildland-proxys3",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'proxys3 = wildland_proxys3.backend:ProxyS3StorageBackend',
        ]
    }
)
