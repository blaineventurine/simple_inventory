from setuptools import setup, find_packages

setup(
    name="simple_inventory",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "custom_components.simple_inventory": []
    }
)
