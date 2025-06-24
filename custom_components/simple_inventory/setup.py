from setuptools import find_packages, setup

setup(
    name="simple_inventory",
    version="0.3.0",
    packages=find_packages(),
    include_package_data=True,
    package_data={"custom_components.simple_inventory": []},
)
