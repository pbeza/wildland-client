from setuptools import setup, find_packages

setup(
    name="wildland-s3",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            's3 = wildland_s3.backend:S3StorageBackend',
        ]
    }
)
